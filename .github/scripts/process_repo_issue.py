#!/usr/bin/env python3

import os
import sys
import logging
from repo_issue_handler import RepoIssueHandler

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    # Get environment variables
    token = os.getenv("GITHUB_TOKEN")
    org_name = os.getenv("ORG_NAME")
    issue_number = os.getenv("ISSUE_NUMBER")
    github_repository = os.getenv("GITHUB_REPOSITORY")

    # Validate environment variables
    required_vars = {
        "GITHUB_TOKEN": token,
        "ORG_NAME": org_name,
        "ISSUE_NUMBER": issue_number,
        "GITHUB_REPOSITORY": github_repository
    }

    missing_vars = [var for var, value in required_vars.items() if not value]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)

    try:
        # Convert issue number to integer
        issue_number = int(issue_number)
        repo_name = github_repository.split("/")[-1]

        # Initialize and run handler
        handler = RepoIssueHandler(token, org_name)
        handler.process_issue(issue_number, repo_name)

    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error processing repository issue: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()