#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/5/11 17:45
@Author  : alexanderwu
@File    : write_code.py
@Modified By: mashenquan, 2023-11-1. In accordance with Chapter 2.1.3 of RFC 116, modify the data type of the `cause_by`
            value of the `Message` object.
@Modified By: mashenquan, 2023-11-27.
        1. Mark the location of Design, Tasks, Legacy Code and Debug logs in the PROMPT_TEMPLATE with markdown
        code-block formatting to enhance the understanding for the LLM.
        2. Following the think-act principle, solidify the task parameters when creating the WriteCode object, rather
        than passing them in when calling the run function.
        3. Encapsulate the input of RunCode into RunCodeContext and encapsulate the output of RunCode into
        RunCodeResult to standardize and unify parameter passing between WriteCode, RunCode, and DebugError.
"""

import json
from pathlib import Path
from typing import Set

from pydantic import Field
from tenacity import retry, wait_random_exponential, stop_after_attempt

from metagpt.actions import Action
from metagpt.actions.project_management_an import REFINED_TASK_LIST, TASK_LIST
from metagpt.actions.write_code_plan_and_change_an import REFINED_TEMPLATE
from metagpt.const import BUGFIX_FILENAME, REQUIREMENT_FILENAME
from metagpt.logs import logger
from metagpt.schema import CodingContext, Document, RunCodeResult
from metagpt.utils.common import CodeParser
from metagpt.utils.project_repo import ProjectRepo

PROMPT_TEMPLATE = """
# File Generation Task

You are generating exactly ONE file: {filename}

## Project Structure
The project has a specific structure:
- Project root/ (e.g., projectname/)
  - package.json (SINGLE package.json for the entire project)
  - frontend/ (Contains all frontend code)
  - backend/ (Contains all backend code)

## CRITICAL INSTRUCTIONS

1. Generate ONLY the file named: {filename}
2. Place this file EXACTLY at the path shown - DO NOT create any nested directories
3. Create complete, functional code - no placeholders
4. Use RELATIVE imports within the project structure

## IMPORTANT PATH RULES:
- ✅ CORRECT: projectname/package.json
- ✅ CORRECT: projectname/frontend/...
- ✅ CORRECT: projectname/backend/...
- ❌ WRONG: projectname/frontend/package.json
- ❌ WRONG: projectname/backend/package.json
- ❌ WRONG: projectname/frontend/frontend/...
- ❌ WRONG: projectname/backend/backend/...

## SPECIAL CASES:
- If {filename} is "package.json", include ALL necessary dependencies for BOTH frontend and backend

## Context for This File

Design Information:
{design}

Task Description:
{task}

Related Code:
```
{code}
```

Debug Information:
```
{logs}
```

Feedback:
{feedback}
"""


class WriteCode(Action):
    name: str = "WriteCode"
    i_context: Document = Field(default_factory=Document)

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
    async def write_code(self, prompt) -> str:
        code_rsp = await self._aask(prompt)
        code = CodeParser.parse_code(block="", text=code_rsp)
        
        # Check for nested directory patterns and alert
        nested_patterns = [
            "frontend/frontend/", 
            "backend/backend/",
            "/project_name/"
        ]
        for pattern in nested_patterns:
            if pattern in code:
                logger.warning(f"Detected potentially problematic nested path: {pattern} in the generated code")
                # We'll let the ensure_critical_files method handle this
        
        return code

    async def ensure_critical_files(self, coding_context: CodingContext, project_repo: ProjectRepo) -> Set[str]:
        added_files = set()
        
        # Define critical files and their minimal content - now a single package.json at project root
        critical_files = {
            "package.json": """{
  "name": "project",
  "version": "1.0.0",
  "description": "A full-stack application",
  "scripts": {
    "start": "concurrently \\"npm run start:frontend\\" \\"npm run start:backend\\"",
    "start:frontend": "cd frontend && react-scripts start",
    "start:backend": "cd backend && node server.js",
    "build": "cd frontend && react-scripts build",
    "test": "cd frontend && react-scripts test",
    "eject": "cd frontend && react-scripts eject"
  },
  "dependencies": {
    "concurrently": "^7.6.0"
  },
  "frontend": {
    "dependencies": {
      "react": "^18.2.0",
      "react-dom": "^18.2.0",
      "react-scripts": "5.0.1"
    }
  },
  "backend": {
    "dependencies": {
      "express": "^4.18.2",
      "cors": "^2.8.5",
      "body-parser": "^1.20.1"
    }
  },
  "browserslist": {
    "production": [
      ">0.2%",
      "not dead",
      "not op_mini all"
    ],
    "development": [
      "last 1 chrome version",
      "last 1 firefox version",
      "last 1 safari version"
    ]
  }
}"""
        }
        
        # Find the project root directory
        if coding_context.code_doc and coding_context.code_doc.root_relative_path:
            # Get the absolute path to the workspace
            workspace_path = Path(coding_context.code_doc.root_path)
            
            logger.info(f"Ensuring critical files in workspace: {workspace_path}")
            
            # Determine if there's a project directory
            filename_parts = Path(coding_context.filename).parts
            project_dir = workspace_path
            
            if len(filename_parts) > 0 and filename_parts[0] not in ['frontend', 'backend', 'package.json']:
                # The first part is likely the project name
                project_name = filename_parts[0]
                project_dir = workspace_path / project_name
                logger.info(f"Using project directory: {project_dir}")
                
                # Make sure frontend and backend directories exist
                frontend_dir = project_dir / "frontend"
                backend_dir = project_dir / "backend"
                frontend_dir.mkdir(parents=True, exist_ok=True)
                backend_dir.mkdir(parents=True, exist_ok=True)
            
            # Create critical files at the project root
            for file_path, content in critical_files.items():
                # Construct the full path
                full_path = project_dir / file_path
                
                # Ensure the directory exists
                full_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Check if file exists
                file_exists = full_path.exists()
                
                if not file_exists:
                    # Create the file
                    try:
                        # Save using the project repo
                        await project_repo.srcs.save(
                            filename=str(full_path),
                            dependencies=list({coding_context.design_doc.root_relative_path, 
                                            coding_context.task_doc.root_relative_path}),
                            content=content,
                        )
                        added_files.add(str(full_path))
                        logger.info(f"Created critical file: {full_path}")
                    except Exception as e:
                        logger.error(f"Failed to create critical file {full_path}: {e}")
                        # Try direct file writing as a fallback
                        try:
                            with open(full_path, 'w') as f:
                                f.write(content)
                            added_files.add(str(full_path))
                            logger.info(f"Created critical file (direct write): {full_path}")
                        except Exception as e2:
                            logger.error(f"Failed direct write for {full_path}: {e2}")
        
        return added_files

    async def run(self, *args, **kwargs) -> CodingContext:
        bug_feedback = await self.repo.docs.get(filename=BUGFIX_FILENAME)
        coding_context = CodingContext.loads(self.i_context.content)
        test_doc = await self.repo.test_outputs.get(filename="test_" + coding_context.filename + ".json")
        requirement_doc = await self.repo.docs.get(filename=REQUIREMENT_FILENAME)
        summary_doc = None
        if coding_context.design_doc and coding_context.design_doc.filename:
            summary_doc = await self.repo.docs.code_summary.get(filename=coding_context.design_doc.filename)
        logs = ""
        if test_doc:
            test_detail = RunCodeResult.loads(test_doc.content)
            logs = test_detail.stderr

        if bug_feedback:
            code_context = coding_context.code_doc.content
        elif self.config.inc:
            code_context = await self.get_codes(
                coding_context.task_doc, exclude=self.i_context.filename, project_repo=self.repo, use_inc=True
            )
        else:
            code_context = await self.get_codes(
                coding_context.task_doc,
                exclude=self.i_context.filename,
                project_repo=self.repo.with_src_path(self.context.src_workspace),
            )

        if self.config.inc:
            prompt = REFINED_TEMPLATE.format(
                user_requirement=requirement_doc.content if requirement_doc else "",
                code_plan_and_change=str(coding_context.code_plan_and_change_doc),
                design=coding_context.design_doc.content if coding_context.design_doc else "",
                task=coding_context.task_doc.content if coding_context.task_doc else "",
                code=code_context,
                logs=logs,
                feedback=bug_feedback.content if bug_feedback else "",
                filename=self.i_context.filename,
                summary_log=summary_doc.content if summary_doc else "",
            )
        else:
            prompt = PROMPT_TEMPLATE.format(
                design=coding_context.design_doc.content if coding_context.design_doc else "",
                task=coding_context.task_doc.content if coding_context.task_doc else "",
                code=code_context,
                logs=logs,
                feedback=bug_feedback.content if bug_feedback else "",
                filename=self.i_context.filename,
                summary_log=summary_doc.content if summary_doc else "",
            )
        
        logger.info(f"Writing {coding_context.filename}..")
        try:
            code = await self.write_code(prompt)
            logger.info(f"Generated code for {coding_context.filename}")
        except Exception as e:
            logger.error(f"Failed to generate code for {coding_context.filename}: {e}")
            code = """"""

        if not coding_context.code_doc:
            # avoid root_path pydantic ValidationError if use WriteCode alone
            root_path = self.context.src_workspace if self.context.src_workspace else ""
            coding_context.code_doc = Document(filename=coding_context.filename, root_path=str(root_path))
        coding_context.code_doc.content = code
        
        # Ensure critical files like package.json are created
        repo_with_src = self.repo.with_src_path(self.context.src_workspace)
        added_files = await self.ensure_critical_files(coding_context, repo_with_src)
        if added_files:
            logger.info(f"Created critical files: {added_files}")
        
        return coding_context

    @staticmethod
    async def get_codes(task_doc: Document, exclude: str, project_repo: ProjectRepo, use_inc: bool = False) -> str:
        """
        Get codes for generating the exclude file in various scenarios.

        Attributes:
            task_doc (Document): Document object of the task file.
            exclude (str): The file to be generated. Specifies the filename to be excluded from the code snippets.
            project_repo (ProjectRepo): ProjectRepo object of the project.
            use_inc (bool): Indicates whether the scenario involves incremental development. Defaults to False.

        Returns:
            str: Codes for generating the exclude file.
        """
        if not task_doc:
            return ""
        if not task_doc.content:
            task_doc = project_repo.docs.task.get(filename=task_doc.filename)
        m = json.loads(task_doc.content)
        code_filenames = m.get(TASK_LIST.key, []) if not use_inc else m.get(REFINED_TASK_LIST.key, [])
        codes = []
        src_file_repo = project_repo.srcs

        # Incremental development scenario
        if use_inc:
            src_files = src_file_repo.all_files
            # Get the old workspace contained the old codes and old workspace are created in previous CodePlanAndChange
            old_file_repo = project_repo.git_repo.new_file_repository(relative_path=project_repo.old_workspace)
            old_files = old_file_repo.all_files
            # Get the union of the files in the src and old workspaces
            union_files_list = list(set(src_files) | set(old_files))
            for filename in union_files_list:
                # Exclude the current file from the all code snippets
                if filename == exclude:
                    # If the file is in the old workspace, use the old code
                    # Exclude unnecessary code to maintain a clean and focused main.py file, ensuring only relevant and
                    # essential functionality is included for the project’s requirements
                    if filename in old_files and filename != "main.py":
                        # Use old code
                        doc = await old_file_repo.get(filename=filename)
                    # If the file is in the src workspace, skip it
                    else:
                        continue
                    codes.insert(0, f"-----Now, {filename} to be rewritten\n```{doc.content}```\n=====")
                # The code snippets are generated from the src workspace
                else:
                    doc = await src_file_repo.get(filename=filename)
                    # If the file does not exist in the src workspace, skip it
                    if not doc:
                        continue
                    codes.append(f"----- {filename}\n```{doc.content}```")

        # Normal scenario
        else:
            for filename in code_filenames:
                # Exclude the current file to get the code snippets for generating the current file
                if filename == exclude:
                    continue
                doc = await src_file_repo.get(filename=filename)
                if not doc:
                    continue
                codes.append(f"----- {filename}\n```{doc.content}```")

        return "\n".join(codes)
