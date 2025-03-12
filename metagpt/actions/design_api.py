#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/5/11 19:26
@Author  : alexanderwu
@File    : design_api.py
@Modified By: mashenquan, 2023/11/27.
            1. According to Section 2.2.3.1 of RFC 135, replace file data in the message with the file name.
            2. According to the design in Section 2.2.3.5.3 of RFC 135, add incremental iteration functionality.
@Modified By: mashenquan, 2023/12/5. Move the generation logic of the project name to WritePRD.
"""
import json
from pathlib import Path
from typing import Optional

from metagpt.actions import Action, ActionOutput
from metagpt.actions.design_api_an import (
    DATA_STRUCTURES_AND_INTERFACES,
    DESIGN_API_NODE,
    PROGRAM_CALL_FLOW,
    REFINED_DATA_STRUCTURES_AND_INTERFACES,
    REFINED_DESIGN_NODE,
    REFINED_PROGRAM_CALL_FLOW,
)
from metagpt.const import DATA_API_DESIGN_FILE_REPO, SEQ_FLOW_FILE_REPO
from metagpt.logs import logger
from metagpt.schema import Document, Documents, Message
from metagpt.utils.mermaid import mermaid_to_file

# Custom template for React/Node.js architecture
REACT_NODE_TEMPLATE = """
# React Frontend and Node.js Backend Application Architecture

## Project Structure
```
project_root/
├── frontend/
│   ├── public/
│   │   ├── index.html
│   │   └── favicon.ico
│   ├── src/
│   │   ├── components/
│   │   │   ├── ComponentA.js
│   │   │   └── ComponentB.js
│   │   ├── App.js
│   │   └── index.js
│   └── package.json
├── backend/
│   ├── controllers/
│   │   └── mainController.js
│   ├── routes/
│   │   └── api.js
│   ├── models/
│   │   └── dataModel.js
│   ├── server.js
│   └── package.json
└── README.md
```

## Frontend (React)
- Create actual component files with complete implementations
- Use functional components with React Hooks
- Implement state management appropriate to application complexity
- Build clean component hierarchy with proper props passing
- Apply responsive design principles

## Backend (Node.js/Express)
- Implement complete RESTful API endpoints
- Create actual controller files with full implementations
- Create complete route files with proper endpoints
- Implement error handling middleware
- Include request validation

## Data Flow
1. User interacts with React frontend
2. Frontend makes API calls to backend services
3. Backend processes requests and returns responses
4. Frontend updates UI based on response data

## Development Guidelines
1. Write clean, self-explanatory code without comments
2. Follow single responsibility principle for components
3. Use descriptive variable and function names
4. Only implement requested features - avoid feature creep
5. Ensure proper error handling throughout the application
"""

NEW_REQ_TEMPLATE = """
### Legacy Content
{old_design}

### New Requirements
{context}
"""


class WriteDesign(Action):
    name: str = ""
    i_context: Optional[str] = None
    desc: str = (
        "Based on the PRD, think about the system design, and design the corresponding APIs, "
        "data structures, library tables, processes, and paths. Please provide your design, feedback "
        "clearly and in detail."
    )

    async def run(self, with_messages: Message, schema: str = None):
        # Use `git status` to identify which PRD documents have been modified in the `docs/prd` directory.
        changed_prds = self.repo.docs.prd.changed_files
        # Use `git status` to identify which design documents in the `docs/system_designs` directory have undergone
        # changes.
        changed_system_designs = self.repo.docs.system_design.changed_files

        # For those PRDs and design documents that have undergone changes, regenerate the design content.
        changed_files = Documents()
        for filename in changed_prds.keys():
            doc = Document(filename=filename, content=REACT_NODE_TEMPLATE)
            changed_files.docs[filename] = doc
            # Save the document
            await self.repo.docs.system_design.save(
                filename=filename, content=REACT_NODE_TEMPLATE, dependencies=[str(self.repo.docs.prd.workdir / filename)]
            )

        # Process any remaining system design files that weren't handled above
        for filename in changed_system_designs.keys():
            if filename in changed_files.docs:
                continue
            doc = await self._update_system_design(filename=filename)
            changed_files.docs[filename] = doc
            
        if not changed_files.docs:
            logger.info("Nothing has changed.")
            
        return ActionOutput(content=changed_files.model_dump_json(), instruct_content=changed_files)

    async def _new_system_design(self, context):
        node = await DESIGN_API_NODE.fill(context=context, llm=self.llm)
        return node

    async def _merge(self, prd_doc, system_design_doc):
        context = NEW_REQ_TEMPLATE.format(old_design=system_design_doc.content, context=prd_doc.content)
        node = await REFINED_DESIGN_NODE.fill(context=context, llm=self.llm)
        system_design_doc.content = node.instruct_content.model_dump_json()
        return system_design_doc

    async def _update_system_design(self, filename) -> Document:
        prd = await self.repo.docs.prd.get(filename)
        old_system_design_doc = await self.repo.docs.system_design.get(filename)
        if not old_system_design_doc:
            system_design = await self._new_system_design(context=prd.content)
            doc = await self.repo.docs.system_design.save(
                filename=filename,
                content=system_design.instruct_content.model_dump_json(),
                dependencies={prd.root_relative_path},
            )
        else:
            doc = await self._merge(prd_doc=prd, system_design_doc=old_system_design_doc)
            await self.repo.docs.system_design.save_doc(doc=doc, dependencies={prd.root_relative_path})
        await self._save_data_api_design(doc)
        await self._save_seq_flow(doc)
        await self.repo.resources.system_design.save_pdf(doc=doc)
        return doc

    async def _save_data_api_design(self, design_doc):
        m = json.loads(design_doc.content)
        data_api_design = m.get(DATA_STRUCTURES_AND_INTERFACES.key) or m.get(REFINED_DATA_STRUCTURES_AND_INTERFACES.key)
        if not data_api_design:
            return
        pathname = self.repo.workdir / DATA_API_DESIGN_FILE_REPO / Path(design_doc.filename).with_suffix("")
        await self._save_mermaid_file(data_api_design, pathname)
        logger.info(f"Save class view to {str(pathname)}")

    async def _save_seq_flow(self, design_doc):
        m = json.loads(design_doc.content)
        seq_flow = m.get(PROGRAM_CALL_FLOW.key) or m.get(REFINED_PROGRAM_CALL_FLOW.key)
        if not seq_flow:
            return
        pathname = self.repo.workdir / Path(SEQ_FLOW_FILE_REPO) / Path(design_doc.filename).with_suffix("")
        await self._save_mermaid_file(seq_flow, pathname)
        logger.info(f"Saving sequence flow to {str(pathname)}")

    async def _save_mermaid_file(self, data: str, pathname: Path):
        pathname.parent.mkdir(parents=True, exist_ok=True)
        await mermaid_to_file(self.config.mermaid.engine, data, pathname)
