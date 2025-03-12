#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A robust wrapper script for running MetaGPT with safeguards against rate limiting.
This script adds:
1. Pre-runtime validation of the MetaGPT environment
2. Better handling of prompts and rate limits
3. Project size constraints to avoid API limits
4. Post-generation validation of created files
"""

import os
import sys
import time
import json
import argparse
import signal
import subprocess
from datetime import datetime
import re

def check_prerequisites():
    """Check that all prerequisites are installed."""
    try:
        import metagpt
        print(f"✅ MetaGPT is installed")
    except ImportError:
        print("❌ MetaGPT is not installed. Please install it first.")
        sys.exit(1)
    
    # Check if config file exists
    config_path = os.path.join(os.getcwd(), "config", "config2.yaml")
    if not os.path.exists(config_path):
        print(f"❌ Config file not found at {config_path}")
        sys.exit(1)
    else:
        print(f"✅ Config file found at {config_path}")

def simplify_idea(idea, level=1):
    """Simplify the idea to a more manageable scope based on level."""
    simplified = idea.strip()
    
    if level >= 1:
        # Level 1: Remove complex features
        for feature in ["authentication", "user accounts", "social sharing", "analytics", 
                        "notifications", "real-time", "payment", "subscription"]:
            simplified = re.sub(r'\b' + feature + r'\b', '', simplified, flags=re.IGNORECASE)
    
    if level >= 2:
        # Level 2: Reduce to core functionality
        simplified = simplified.replace("with categories", "")
        simplified = simplified.replace("with priorities", "")
        simplified = simplified.replace("with due dates", "")
        simplified = simplified.replace("with tags", "")
        simplified = simplified.replace("with labels", "")
        simplified = simplified.replace("with reminders", "")
        
    if level >= 3:
        # Level 3: Minimize to bare essentials
        patterns = [
            (r'A (complex|sophisticated|feature-rich|advanced) ', 'A simple '),
            (r'An (complex|sophisticated|feature-rich|advanced) ', 'A simple '),
            (r'(and|with) \w+ \w+ \w+ \w+', ''),
            (r'(and|with) \w+ \w+ \w+', ''),
            (r'(and|with) \w+ \w+', '')
        ]
        for pattern, replacement in patterns:
            simplified = re.sub(pattern, replacement, simplified, flags=re.IGNORECASE)
            
        # Ensure it still makes sense as an app description
        if not any(word in simplified.lower() for word in ['app', 'website', 'tool', 'system', 'application']):
            simplified += " app"
    
    # Clean up and normalize
    simplified = re.sub(r'\s+', ' ', simplified).strip()
    simplified = re.sub(r'^\s*[aA]\s+', 'A ', simplified)  # Ensure proper capitalization
    simplified = re.sub(r'^\s*[aA]n\s+', 'An ', simplified)
    
    return simplified

def set_timeout(seconds):
    """Set a timeout for the script."""
    def timeout_handler(signum, frame):
        print(f"\n⏱️ Timeout reached after {seconds} seconds.")
        print("The process is taking too long, likely due to rate limits or other issues.")
        print("You can try again later with a simpler project idea.")
        sys.exit(1)
    
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)

def verify_generated_files(workspace_dir):
    """Verify that the generated files are valid and contain actual code."""
    # Get the latest project directory
    project_dirs = [os.path.join(workspace_dir, d) for d in os.listdir(workspace_dir) 
                  if os.path.isdir(os.path.join(workspace_dir, d))]
    
    if not project_dirs:
        print("❌ No project directories found in workspace.")
        return False
    
    # Sort by modification time
    project_dirs.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    latest_project = project_dirs[0]
    
    print(f"📁 Verifying generated files in {latest_project}")
    
    # Find all python files
    py_files = []
    for root, dirs, files in os.walk(latest_project):
        for file in files:
            if file.endswith('.py') or file.endswith('.html') or file.endswith('.js'):
                py_files.append(os.path.join(root, file))
    
    if not py_files:
        print("❌ No code files found in the project.")
        return False
    
    valid_files = 0
    problem_files = []
    
    for file_path in py_files:
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                
            # Check if file contains actual code
            if len(content.strip()) < 50:
                problem_files.append(f"{os.path.basename(file_path)} (too short)")
            elif "I can't rewrite" in content or "Without this information" in content:
                problem_files.append(f"{os.path.basename(file_path)} (contains error messages)")
            else:
                valid_files += 1
                
        except Exception as e:
            problem_files.append(f"{os.path.basename(file_path)} (error: {str(e)})")
    
    print(f"✅ Valid files: {valid_files}")
    if problem_files:
        print(f"⚠️ Problem files: {len(problem_files)}")
        for file in problem_files[:5]:  # Show first 5 problem files
            print(f"  - {file}")
        
    return valid_files > 0

def main():
    """Main function to run the MetaGPT wrapper."""
    parser = argparse.ArgumentParser(description="Run MetaGPT with rate limit safeguards")
    parser.add_argument("idea", nargs="?", help="Your app idea", default="Build a simple todo app")
    parser.add_argument("--no-implement", action="store_true", help="Skip code implementation")
    parser.add_argument("--no-code-review", action="store_true", help="Skip code review")
    parser.add_argument("--investment", type=float, default=2.5, help="Investment amount (default: 2.5)")
    parser.add_argument("--simple", type=int, choices=[0, 1, 2, 3], default=0, 
                        help="Simplification level (0=none, 3=max)")
    parser.add_argument("--timeout", type=int, default=1800, help="Timeout in seconds (default: 1800)")
    parser.add_argument("--verify", action="store_true", help="Verify generated files after completion")
    parser.add_argument("--n-round", type=int, default=3, help="Number of rounds (default: 3)")
    args = parser.parse_args()

    # Check prerequisites
    check_prerequisites()
    
    # Set timeout
    set_timeout(args.timeout)
    
    # Print current time
    print(f"⏳ Starting MetaGPT run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📋 Project idea: {args.idea}")

    # Process the idea based on simplification level
    if args.simple > 0:
        original_idea = args.idea
        idea = simplify_idea(args.idea, args.simple)
        print(f"🔄 Simplification level {args.simple} applied")
        print(f"📝 Simplified idea: {idea}")
    else:
        idea = args.idea

    # Check if MetaGPT is installed
    try:
        subprocess.run(["pip", "show", "metagpt"], stdout=subprocess.DEVNULL, check=True)
        print("✅ MetaGPT is installed")
    except subprocess.CalledProcessError:
        print("❌ MetaGPT is not installed. Please install it using: pip install metagpt")
        sys.exit(1)

    # Check if config file exists
    config_path = os.path.expanduser(os.path.join(os.getcwd(), "config/config2.yaml"))
    if os.path.exists(config_path):
        print(f"✅ Config file found at {config_path}")
    else:
        print("❌ Config file not found. Please create a config file at config/config2.yaml")
        sys.exit(1)

    # Prepare command to run MetaGPT - ensure code generation happens
    cmd = [
        "python3", "-m", "metagpt.software_company",
        idea,  # Pass idea as a positional argument
        "--investment", str(args.investment)
    ]
    
    # Add n-round parameter
    cmd.extend(["--n-round", str(args.n_round)])
    
    if args.no_implement:
        cmd.append("--no-implement")
    
    if args.no_code_review:
        cmd.append("--no-code-review")

    # Print command for debugging
    print(f"🧠 Running command: {' '.join(cmd)}")
    
    # Brief wait before starting to avoid rate limit issues
    print(f"⏳ Waiting 5 seconds before starting...")
    time.sleep(5)
    
    # Run MetaGPT with command - stream output in real-time
    print(f"🚀 Running MetaGPT. This process may take several minutes to complete...")
    
    try:
        # Use Popen to stream output in real-time
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        # Print output in real-time
        for line in process.stdout:
            print(line, end='')
            
        # Wait for process to complete
        return_code = process.wait()
        
        # Check return code
        if return_code == 0:
            print("✅ MetaGPT completed successfully")
            if args.verify:
                # Verify generated files
                workspace_dir = os.path.join(os.getcwd(), "workspace")
                if os.path.exists(workspace_dir):
                    print(f"🔍 Verifying generated files in {workspace_dir}...")
                    if verify_generated_files(workspace_dir):
                        print("✅ Generated files verification passed")
                    else:
                        print("⚠️ Some files may have issues. Please check manually.")
                else:
                    print(f"❌ Workspace directory not found at {workspace_dir}")
        else:
            print(f"❌ MetaGPT encountered an error (return code: {return_code})")
            
    except KeyboardInterrupt:
        print("\n⚠️ Process interrupted by user.")
        return 1
    except Exception as e:
        print(f"❌ Error running MetaGPT: {e}")
        return 1
        
    print(f"⏳ Finished MetaGPT run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return return_code

if __name__ == "__main__":
    sys.exit(main()) 