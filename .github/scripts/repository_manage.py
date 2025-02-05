import os
import yaml
import sys
import logging
from github import Github, GithubException
from github.Repository import Repository


class RepositoryConfigManager:
    def __init__(self, github_token, organization):
        """
        Initialize the repository configuration manager.

        :param github_token: GitHub Personal Access Token with repo and org permissions
        :param organization: GitHub organization name
        """
        self.g = Github(github_token)
        self.org = self.g.get_organization(organization)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger = logging.getLogger(__name__)

    def load_default_config(self, config_path="default_repository.yml"):
        """
        Load the default repository configuration.

        :param config_path: Path to the default repository configuration file
        :return: Parsed configuration dictionary
        """
        try:
            with open(config_path, "r") as file:
                return yaml.safe_load(file)["repository"]
        except FileNotFoundError:
            self.logger.error(f"Default configuration file not found at {config_path}")
            sys.exit(1)
        except yaml.YAMLError as e:
            self.logger.error(f"Error parsing YAML file: {e}")
            sys.exit(1)

    def create_or_update_repository_config(self, repo_name, default_config, workspace_path):
        """
        Create or update repository configuration in the centralized repository.

        :param repo_name: Name of the repository
        :param default_config: Default configuration dictionary
        :param workspace_path: Path to the GitHub Actions workspace
        """
        try:
            # Ensure repositories directory exists
            repositories_dir = os.path.join(workspace_path, "repositories")
            os.makedirs(repositories_dir, exist_ok=True)

            # Create repository-specific directory
            repo_config_dir = os.path.join(repositories_dir, repo_name)
            os.makedirs(repo_config_dir, exist_ok=True)

            # Path for the repository configuration file
            config_file_path = os.path.join(repo_config_dir, "repository.yml")

            # Prepare configuration dictionary
            config_to_save = {"repository": default_config}

            # Write the configuration file
            with open(config_file_path, "w") as file:
                yaml.dump(config_to_save, file, default_flow_style=False)

            self.logger.info(f"Created/Updated repository configuration for {repo_name}")
            return config_file_path

        except Exception as e:
            self.logger.error(f"Error creating repository configuration for {repo_name}: {e}")
            sys.exit(1)

    def create_or_update_github_repository(self, repo_name, default_config):
        """
        Create a new repository or update an existing one based on configuration.

        :param repo_name: Name of the repository
        :param default_config: Default configuration dictionary
        """
        try:
            # Check if repository exists
            try:
                repo = self.org.get_repo(repo_name)
                self.logger.info(f"Repository {repo_name} already exists.")
                update_mode = True
            except GithubException:
                # Repository doesn't exist, create it
                repo = self.org.create_repo(
                    name=repo_name,
                    private=default_config.get("visibility", "private") == "private",
                    auto_init=True,  # Initialize with README
                )
                self.logger.info(f"Created new repository {repo_name}")
                update_mode = False

            # Update repository settings
            self._update_repo_settings(repo, default_config)

            return repo

        except Exception as e:
            self.logger.error(f"Error processing repository {repo_name}: {e}")
            sys.exit(1)

    def _update_repo_settings(self, repo: Repository, config: dict):
        """
        Update repository settings based on configuration.

        :param repo: GitHub Repository object
        :param config: Configuration dictionary
        """
        # Mapping of configuration keys to repository edit parameters
        setting_map = {
            "has_issues": "has_issues",
            "has_projects": "has_projects",
            "has_wiki": "has_wiki",
            "default_branch": "default_branch",
            "allow_squash_merge": "allow_squash_merge",
            "allow_merge_commit": "allow_merge_commit",
            "allow_rebase_merge": "allow_rebase_merge",
            "allow_auto_merge": "allow_auto_merge",
            "delete_branch_on_merge": "delete_branch_on_merge",
            "allow_update_branch": "allow_update_branch",
            "archived": "archived",
        }

        # Prepare edit parameters
        edit_params = {
            github_param: config.get(config_key, getattr(repo, github_param))
            for config_key, github_param in setting_map.items()
        }

        # Remove default_branch from edit_params for newly created repos
        if not repo.get_branches():
            edit_params.pop("default_branch", None)

        # Update security settings
        if config.get("security", {}).get("enableVulnerabilityAlerts", False):
            try:
                repo.enable_vulnerability_alert()
            except Exception as e:
                self.logger.warning(f"Could not enable vulnerability alerts: {e}")

        if config.get("security", {}).get("enableAutomatedSecurityFixes", False):
            try:
                repo.enable_automated_security_fixes()
            except Exception as e:
                self.logger.warning(f"Could not enable automated security fixes: {e}")

        # Update repository topics
        topics = config.get("topics", [])
        if topics:
            repo.replace_topics(topics)

        # Edit repository settings, handling potential branch issues
        try:
            repo.edit(**edit_params)
            self.logger.info(f"Updated repository settings for {repo.name}")
        except GithubException as e:
            # Log the specific error, but don't exit
            self.logger.warning(f"Could not update all repository settings: {e}")


def main():
    # Get environment variables
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
    GITHUB_ORGANIZATION = os.environ.get("GITHUB_ORGANIZATION")
    GITHUB_WORKSPACE = os.environ.get("GITHUB_WORKSPACE", os.getcwd())
    REPOSITORY_NAME = os.environ.get("REPOSITORY_NAME")

    # Validate required environment variables
    if not all([GITHUB_TOKEN, GITHUB_ORGANIZATION, REPOSITORY_NAME]):
        logging.error("Missing required environment variables")
        sys.exit(1)

    # Initialize manager
    manager = RepositoryConfigManager(GITHUB_TOKEN, GITHUB_ORGANIZATION)

    # Load default configuration
    default_config = manager.load_default_config()

    # Override repository name if provided in environment
    repo_name = REPOSITORY_NAME or default_config["name"]

    # Create/update repository configuration in the centralized repo
    config_file_path = manager.create_or_update_repository_config(repo_name, default_config, GITHUB_WORKSPACE)

    # Create or update the GitHub repository
    manager.create_or_update_github_repository(repo_name, default_config)

    # Log the configuration file path for potential further use
    print(f"Repository configuration created at: {config_file_path}")


if __name__ == "__main__":
    main()
