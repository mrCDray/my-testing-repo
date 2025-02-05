#!/usr/bin/env python3

import os
import sys
import logging
from repo_sync_manager import RepoSyncManager

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

    if not all([token, org_name]):
        logger.error("Missing required environment variables")
        sys.exit(1)

    try:
        # Initialize sync manager
        sync_manager = RepoSyncManager(token, org_name)
        
        # Sync all repositories
        results = sync_manager.sync_all_repositories()
        
        # Log results
        for repo_name, changes in results.items():
            if isinstance(changes, str) and changes.startswith("Error"):
                logger.error(f"{repo_name}: {changes}")
            else:
                if changes:
                    logger.info(f"{repo_name} changes: {changes}")
                else:
                    logger.info(f"{repo_name}: No changes needed")

    except Exception as e:
        logger.error(f"Sync failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()