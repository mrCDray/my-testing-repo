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
        """Create repository.yml config file if it doesn't exist"""
        try:
            # Check if file already exists
            try:
                repo.get_contents("repository.yml")
                self.logger.debug("repository.yml already exists, skipping creation")
                return
            except Exception:
                # File doesn't exist, create it
                config_content = yaml.dump(config, default_flow_style=False)
                repo.create_file("repository.yml", "Initial repository configuration", config_content)
                self.logger.info("Created repository.yml file")

        except Exception as e:
            self.logger.error(f"Error creating config file: {str(e)}")
            raise

    def _apply_visibility_settings(self, repo: Repository, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply visibility settings to repository"""
        changes = {}
        visibility = config.get("visibility")

        if visibility and visibility in ["public", "private", "internal"]:
            try:
                # Get current visibility
                current_visibility = "private" if repo.private else "public"
                if hasattr(repo, "visibility"):
                    current_visibility = repo.visibility

                if current_visibility != visibility:
                    repo.edit(visibility=visibility)
                    changes["visibility"] = f"{current_visibility} → {visibility}"

            except Exception as e:
                self.logger.error(f"Error updating visibility: {str(e)}")

        return changes

    def _sync_rulesets(self, repo: Repository, rulesets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Sync repository rulesets"""
        changes = {}

        try:
            # Get existing rulesets
            existing_rulesets = list(repo.get_rulesets())

            for ruleset_config in rulesets:
                ruleset_name = ruleset_config.get("name")
                if not ruleset_name:
                    continue

                # Find matching existing ruleset
                existing_ruleset = next((r for r in existing_rulesets if r.name == ruleset_name), None)

                ruleset_params = {
                    "name": ruleset_name,
                    "target": ruleset_config.get("target", "branch"),
                    "enforcement": ruleset_config.get("enforcement", "active"),
                    "conditions": ruleset_config.get("conditions", {}),
                    "rules": ruleset_config.get("rules", []),
                }

                if existing_ruleset:
                    # Update existing ruleset
                    existing_ruleset.edit(**ruleset_params)
                    changes[f"ruleset_{ruleset_name}"] = "updated"
                else:
                    # Create new ruleset
                    repo.create_ruleset(**ruleset_params)
                    changes[f"ruleset_{ruleset_name}"] = "created"

            return changes

        except Exception as e:
            self.logger.error(f"Error syncing rulesets: {str(e)}")
            return {"error": str(e)}

    def _sync_status_checks(
        self, repo: Repository, branch_name: str, required_checks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Sync required status checks for a branch"""
        changes = {}

        try:
            branch = repo.get_branch(branch_name)
            current_protection = branch.get_protection()

            # Prepare status checks configuration
            contexts = [check["context"] for check in required_checks]
            strict = any(check.get("strict", False) for check in required_checks)

            # Update branch protection with new status checks
            branch.edit_protection(
                strict=strict,
                contexts=contexts,
                enforce_admins=current_protection.enforce_admins.enabled,
                required_approving_review_count=(
                    current_protection.required_pull_request_reviews.required_approving_review_count
                    if current_protection.required_pull_request_reviews
                    else None
                ),
                dismiss_stale_reviews=(
                    current_protection.required_pull_request_reviews.dismiss_stale_reviews
                    if current_protection.required_pull_request_reviews
                    else False
                ),
            )

            changes[f"status_checks_{branch_name}"] = f"updated: {', '.join(contexts)}"

        except Exception as e:
            self.logger.error(f"Error syncing status checks: {str(e)}")
            changes[f"status_checks_{branch_name}"] = f"error: {str(e)}"

        return changes

    def _sync_repository_with_config(self, repo, config: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronize repository settings with configuration"""
        changes = {}

        try:
            # Update basic repository settings
            repo_config = config.get("repository", {})
            changes.update(self._sync_repo_settings(repo, repo_config))

            # Update visibility settings
            changes.update(self._apply_visibility_settings(repo, repo_config))

            # Update security settings
            if "security" in repo_config:
                changes.update(self._sync_security_settings(repo, repo_config["security"]))

            # Update rulesets
            if "rulesets" in repo_config:
                changes.update(self._sync_rulesets(repo, repo_config["rulesets"]))

            # Update required status checks for each branch
            if "status_checks" in repo_config:
                for branch_config in repo_config["status_checks"]:
                    branch_name = branch_config.get("branch")
                    required_checks = branch_config.get("checks", [])
                    if branch_name and required_checks:
                        changes.update(self._sync_status_checks(repo, branch_name, required_checks))

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
