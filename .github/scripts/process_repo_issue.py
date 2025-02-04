#!/usr/bin/env python3

import os
import sys
import logging
from github import Github, GithubException

from repo_issue_handler import RepoIssueHandler

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    # Get environment variables
    token = os.getenv("GITHUB_TOKEN")
    org_name = os.getenv("ORG_NAME")
    issue_number = os.getenv("ISSUE_NUMBER")
    github_repository = os.getenv("GITHUB_REPOSITORY")

    if not all([token, org_name, issue_number, github_repository]):
        logger.error("Missing required environment variables")
        sys.exit(1)

    try:
        # Convert issue number to integer
        issue_number = int(issue_number)
        repo_name = github_repository.split("/")[-1]
        # Initialize handler
        handler = RepoIssueHandler(token, org_name, repo_name)

        # Get the issue to determine the type
        g = Github(token)
        org = g.get_organization(org_name)
        repo = org.get_repo(repo_name)
        issue = repo.get_issue(number=issue_number)

        logger.info(f"Processing issue #{issue_number}")

        # Check issue labels to determine action
        labels = [label.name for label in issue.labels]

        if "repo-creation" in labels:
            logger.info("Handling repository creation")
            handler.handle_creation_issue(issue_number)
        elif "repo-update" in labels:
            logger.info("Handling repository update")
            handler.handle_update_issue(issue_number)
        else:
            logger.warning(f"Issue #{issue_number} does not have required labels")
            issue.create_comment("This issue needs either 'repo-creation' or 'repo-update' label to be processed.")

    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        sys.exit(1)
    except GithubException as e:
        logger.error(f"GitHub API error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
