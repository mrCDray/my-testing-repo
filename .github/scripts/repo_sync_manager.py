import logging
from typing import Dict, Any, List, Optional

import yaml
from github import Github
from github.Repository import Repository


class RepoSyncManager:
    def __init__(self, token: str, org_name: str):
        self.github = Github(token)
        self.org = self.github.get_organization(org_name)
        self.logger = logging.getLogger(__name__)
        self.default_config = self._load_default_config()

    def _load_default_config(self) -> Dict[str, Any]:
        """Load default repository configuration"""
        try:
            with open("default_repository.yml", mode="r", encoding="utf-8") as file:
                return yaml.safe_load(file)
        except (OSError, yaml.YAMLError) as error:
            self.logger.error(f"Error loading default config: {str(error)}")
            raise

    def create_repository(
        self, repo_name: str, config: Dict[str, Any], template_repo_name: Optional[str] = None
    ) -> None:
        """Create a new repository using template or default settings"""
        try:
            # Check if repository already exists
            if self._repository_exists(repo_name):
                raise ValueError(f"Repository {repo_name} already exists")

            # Merge provided config with default config
            merged_config = self.default_config.copy()
            self._merge_configs(merged_config, config)

            if template_repo_name:
                # Create from template
                template_repo = self.org.get_repo(template_repo_name)
                repo = self.org.create_repository_from_template(
                    name=repo_name,
                    template_repository=template_repo,
                    private=(merged_config["repository"]["visibility"] == "private"),
                )
            else:
                # Create with default settings
                repo = self.org.create_repo(
                    name=repo_name,
                    description=merged_config["repository"].get("description", ""),
                    private=(merged_config["repository"]["visibility"] == "private"),
                    auto_init=True,
                )

            # Apply configuration
            self._apply_repository_config(repo, merged_config)

            # Create repository.yml in the new repository
            self._create_repository_config_file(repo, merged_config)

            self.logger.info(f"Successfully created repository: {repo_name}")

        except Exception as e:
            self.logger.error(f"Error creating repository {repo_name}: {str(e)}")
            raise

    def update_repository(self, repo_name: str, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing repository with new configuration"""
        try:
            repo = self.org.get_repo(repo_name)
            current_config = self._get_repository_config(repo)

            # Merge new config with current config
            merged_config = current_config.copy()
            self._merge_configs(merged_config, new_config)

            # Apply changes and track what was updated
            changes = self._sync_repository_with_config(repo, merged_config)

            # Update repository.yml with merged config
            self._create_repository_config_file(repo, merged_config)

            return changes

        except Exception as e:
            self.logger.error(f"Error updating repository {repo_name}: {str(e)}")
            raise

    def sync_all_repositories(self) -> Dict[str, Any]:
        """Sync all repositories with their configuration files"""
        sync_results = {}

        try:
            for repo in self.org.get_repos():
                try:
                    config = self._get_repository_config(repo)
                    changes = self._sync_repository_with_config(repo, config)

                    if changes:
                        sync_results[repo.name] = changes
                        self.logger.info(f"Synced repository {repo.name}: {changes}")

                except Exception as e:
                    sync_results[repo.name] = f"Error: {str(e)}"
                    self.logger.error(f"Error syncing repository {repo.name}: {str(e)}")

            return sync_results

        except Exception as e:
            self.logger.error(f"Error during repository sync: {str(e)}")
            raise

    def _repository_exists(self, repo_name: str) -> bool:
        """Check if repository exists in organization"""
        try:
            self.org.get_repo(repo_name)
            return True
        except Exception as error:
            self.logger.debug(f"Repository check failed: {str(error)}")
            return False

    def _get_repository_config(self, repo: Repository) -> Dict[str, Any]:
        """Get repository configuration from repository.yml"""
        try:
            config_file = repo.get_contents("repository.yml")
            return yaml.safe_load(config_file.decoded_content)
        except Exception as error:
            self.logger.debug(f"Config file not found, using defaults: {str(error)}")
            return self.default_config.copy()

    def _merge_configs(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """Merge configurations recursively"""
        for key, value in source.items():
            if isinstance(value, dict) and key in target:
                self._merge_configs(target[key], value)
            elif value is not None:
                target[key] = value

    def _create_repository_config_file(self, repo, config: Dict[str, Any]) -> None:
        """Create or update repository.yml config file"""
        try:
            config_content = yaml.dump(config, default_flow_style=False)

            try:
                file = repo.get_contents("repository.yml")
                repo.update_file("repository.yml", "Update repository configuration", config_content, file.sha)
            except:
                repo.create_file("repository.yml", "Initial repository configuration", config_content)

        except Exception as e:
            self.logger.error(f"Error creating/updating config file: {str(e)}")
            raise

    def _sync_repository_with_config(self, repo, config: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronize repository settings with configuration"""
        changes = {}

        try:
            # Update basic repository settings
            repo_config = config.get("repository", {})
            changes.update(self._sync_repo_settings(repo, repo_config))

            # Update security settings
            if "security" in config:
                changes.update(self._sync_security_settings(repo, config["security"]))

            # Update branch protection rules
            if "rulesets" in config:
                changes.update(self._sync_branch_protection(repo, config["rulesets"]))

            # Update custom properties
            if "custom_properties" in config:
                changes.update(self._sync_custom_properties(repo, config["custom_properties"]))

            return changes

        except Exception as e:
            self.logger.error(f"Error syncing repository settings: {str(e)}")
            raise

    def _sync_repo_settings(self, repo, config: Dict[str, Any]) -> Dict[str, Any]:
        """Sync basic repository settings"""
        changes = {}
        settable_attrs = [
            "has_issues",
            "has_projects",
            "has_wiki",
            "default_branch",
            "allow_squash_merge",
            "allow_merge_commit",
            "allow_rebase_merge",
            "allow_auto_merge",
            "delete_branch_on_merge",
        ]

        update_dict = {}
        for attr in settable_attrs:
            if attr in config and getattr(repo, attr) != config[attr]:
                update_dict[attr] = config[attr]
                changes[attr] = f"{getattr(repo, attr)} → {config[attr]}"

        if update_dict:
            repo.edit(**update_dict)

        return changes

    def _sync_security_settings(self, repo, config: Dict[str, Any]) -> Dict[str, Any]:
        """Sync security settings"""
        changes = {}

        if config.get("enableVulnerabilityAlerts"):
            repo.enable_vulnerability_alert()
            changes["vulnerability_alerts"] = "enabled"

        if config.get("enableAutomatedSecurityFixes"):
            repo.enable_automated_security_fixes()
            changes["automated_security_fixes"] = "enabled"

        return changes

    def _sync_branch_protection(self, repo: Repository, rulesets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Sync branch protection rules"""
        changes = {}
        try:
            for rule in rulesets:
                branch_pattern = rule.get("pattern")
                if not branch_pattern:
                    continue

                protection_settings = {
                    "required_status_checks": rule.get("required_status_checks", None),
                    "enforce_admins": rule.get("enforce_admins", True),
                    "required_pull_request_reviews": rule.get("required_reviews", None),
                    "restrictions": rule.get("restrictions", None),
                }

                repo.get_branch(branch_pattern).edit_protection(**protection_settings)
                changes[branch_pattern] = "protection rules updated"

        except Exception as error:
            self.logger.error(f"Error updating branch protection: {str(error)}")

        return changes

    def _sync_custom_properties(self, repo: Repository, properties: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Sync custom properties"""
        changes = {}
        try:
            for property_config in properties:
                property_name = property_config.get("name")
                if not property_name:
                    continue

                # Note: This is a placeholder for the actual implementation
                # GitHub's API for custom properties might require specific handling
                self.logger.info(f"Would set custom property {property_name} for {repo.name}")
                changes[property_name] = "property update simulated"

        except Exception as error:
            self.logger.error(f"Error updating custom properties: {str(error)}")

        return changes

    def _apply_repository_config(self, repo: Repository, config: Dict[str, Any]) -> None:
        """Apply initial configuration to newly created repository"""
        try:
            self._sync_repo_settings(repo, config.get("repository", {}))
            if "security" in config:
                self._sync_security_settings(repo, config["security"])
            if "rulesets" in config:
                self._sync_branch_protection(repo, config["rulesets"])
            if "custom_properties" in config:
                self._sync_custom_properties(repo, config["custom_properties"])
        except Exception as error:
            self.logger.error(f"Error applying repository config: {str(error)}")
            raise
