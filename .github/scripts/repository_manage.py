import os
import yaml
import sys
import logging
from github import Github, GithubException
from github.Repository import Repository


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


class RepositoryConfigManager:
    def __init__(self, github_token, organization):
        """
        Initialize the repository configuration manager.

        :param github_token: GitHub Personal Access Token with repo and org permissions
        :param organization: GitHub organization name
        """
        self.g = Github(github_token)
        self.org = self.g.get_organization(organization)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("repository_manage.log")],
        )
        self.logger = logging.getLogger(__name__)

    def load_repository_config(self, config_path, repository_name=None):
        """
        Load repository configuration, with advanced name handling.

        :param config_path: Path to the repository configuration file
        :param repository_name: Optional repository name to override config
        :return: Tuple of (parsed configuration dictionary, repository name)
        """
        try:
            # First, try to load the specific repository configuration
            if os.path.exists(config_path):
                with open(config_path, "r") as file:
                    config = yaml.safe_load(file)
                    repo_config = config.get("repository", {})

                    # Prioritize passed repository name, then config name, then default
                    if repository_name:
                        repo_name = str(repository_name)
                    elif repo_config.get("name") and repo_config["name"] != "[repository-name]":
                        repo_name = str(repo_config["name"])
                    else:
                        repo_name = "default-repository"

                    # Replace placeholder name if needed
                    if repo_config.get("name") == "[repository-name]":
                        repo_config["name"] = repo_name

                    return repo_config, repo_name

            # If no specific config, load default configuration
            default_config_path = "default_repository.yml"
            if os.path.exists(default_config_path):
                with open(default_config_path, "r") as file:
                    config = yaml.safe_load(file)
                    repo_config = config.get("repository", {})

                    # Use passed name or default
                    repo_name = str(repository_name or repo_config.get("name", "default-repository"))

                    # Replace placeholder name
                    if repo_config.get("name") == "[repository-name]":
                        repo_config["name"] = repo_name

                    return repo_config, repo_name

            # If no configuration found at all
            self.logger.warning("No configuration found. Using minimal defaults.")
            repo_name = str(repository_name or "default-repository")
            return {"name": repo_name}, repo_name

        except (FileNotFoundError, yaml.YAMLError) as e:
            self.logger.error(f"Error loading configuration: {e}")
            repo_name = str(repository_name or "default-repository")
            return {"name": repo_name}, repo_name

    def create_or_update_repository_config(self, repo_name, config, workspace_path):
        """
        Create or update repository configuration in the centralized repository.

        :param repo_name: Name of the repository
        :param config: Configuration dictionary
        :param workspace_path: Path to the GitHub Actions workspace
        :return: Path to the created/updated configuration file
        """
        try:
            # Ensure repository name is a string and not the placeholder
            repo_name = str(repo_name)
            if config.get("name") == "[repository-name]":
                config["name"] = repo_name

            # Ensure repositories directory exists
            repositories_dir = os.path.join(workspace_path, "repositories")
            os.makedirs(repositories_dir, exist_ok=True)

            # Create repository-specific directory
            repo_config_dir = os.path.join(repositories_dir, repo_name)
            os.makedirs(repo_config_dir, exist_ok=True)

            # Path for the repository configuration file
            config_file_path = os.path.join(repo_config_dir, "repository.yml")

            # Prepare configuration dictionary
            config_to_save = {"repository": config}

            # Write the configuration file
            with open(config_file_path, "w") as file:
                yaml.dump(
                    config_to_save, file, sort_keys=False, Dumper=IndentDumper, default_flow_style=False, indent=2
                )

            self.logger.info(f"Created/Updated repository configuration for {repo_name}")
            return config_file_path

        except Exception as e:
            self.logger.error(f"Error creating repository configuration for {repo_name}: {e}")
            raise

    def create_or_update_github_repository(self, repo_name, config):
        """
        Create a new repository or update an existing one based on configuration.

        :param repo_name: Name of the repository
        :param config: Configuration dictionary
        :return: Repository object
        """
        try:
            # Validate and set a default repository name
            repo_name = str(repo_name or config.get("name", "default-repository"))

            # Check if repository exists
            try:
                repo = self.org.get_repo(repo_name)
                self.logger.info(f"Repository {repo_name} already exists.")
                update_mode = True
            except GithubException:
                # Repository doesn't exist, create it
                repo = self.org.create_repo(
                    name=repo_name,
                    private=config.get("visibility", "private") == "private",
                    auto_init=True,  # Initialize with README
                )
                self.logger.info(f"Created new repository {repo_name}")
                update_mode = False

            # Update repository settings
            self._update_repo_settings(repo, config)

            return repo

        except Exception as e:
            self.logger.error(f"Error processing repository {repo_name}: {e}")
            raise

    def _update_repo_settings(self, repo: Repository, config: dict):
        """
        Update repository settings based on configuration.

        :param repo: GitHub Repository object
        :param config: Configuration dictionary
        """
        # Comprehensive setting map
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
        security_config = config.get("security", {})
        if security_config.get("enableVulnerabilityAlerts", False):
            try:
                repo.enable_vulnerability_alert()
            except Exception as e:
                self.logger.warning(f"Could not enable vulnerability alerts: {e}")

        if security_config.get("enableAutomatedSecurityFixes", False):
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
            # Log the specific error, but continue
            self.logger.warning(f"Could not update all repository settings: {e}")


def main():
    # Enhanced environment variable handling (same as previous implementation)
    def get_env_var(var_name, default=None, required=True):
        value = os.environ.get(var_name, default)
        if required and not value:
            raise ValueError(f"Missing required environment variable: {var_name}")
        return value

    try:
        # Retrieve environment variables with enhanced error handling
        GITHUB_TOKEN = get_env_var("GITHUB_TOKEN")
        GITHUB_ORGANIZATION = get_env_var("GITHUB_ORGANIZATION")
        GITHUB_WORKSPACE = get_env_var("GITHUB_WORKSPACE", default=os.getcwd(), required=False)

        # Determine repository name with advanced logic
        REPOSITORY_NAME = os.environ.get("REPOSITORY_NAME") or os.environ.get("INPUT_REPOSITORY_NAME")

        # If no repository name is provided, try to determine from changed files
        if not REPOSITORY_NAME:
            # Check GitHub event path for push event details
            github_event_path = os.environ.get("GITHUB_EVENT_PATH")
            if github_event_path and os.path.exists(github_event_path):
                with open(github_event_path, "r") as f:
                    import json

                    event_data = json.load(f)

                    # Look for repository configuration files in the changed files
                    changed_files = event_data.get("push", {}).get("files", [])
                    for file in changed_files:
                        file_path = file.get("filename", "")
                        if file_path.startswith("repositories/") and file_path.endswith("/repository.yml"):
                            # Extract repository name from path
                            REPOSITORY_NAME = file_path.split("/")[1]
                            break

        # Initialize manager
        manager = RepositoryConfigManager(GITHUB_TOKEN, GITHUB_ORGANIZATION)

        # Determine configuration file path with more flexibility
        if REPOSITORY_NAME:
            config_path = os.path.join(GITHUB_WORKSPACE, "repositories", str(REPOSITORY_NAME), "repository.yml")
        else:
            config_path = os.path.join(GITHUB_WORKSPACE, "default_repository.yml")

        # Load configuration with optional repository name
        config, repo_name = manager.load_repository_config(config_path, REPOSITORY_NAME)

        # Ensure repository name is a string
        repo_name = str(repo_name)

        # Create/update repository configuration
        config_file_path = manager.create_or_update_repository_config(repo_name, config, GITHUB_WORKSPACE)

        # Create or update the GitHub repository
        manager.create_or_update_github_repository(repo_name, config)

        # Log the configuration file path
        print(f"Repository configuration created/updated at: {config_file_path}")

    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
