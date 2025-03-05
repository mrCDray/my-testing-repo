"""Test module for team_manage_parent_teams.py."""

import os
import sys
from pathlib import Path
from unittest.mock import patch, call, MagicMock
import pytest
from pytest_mock.plugin import _mocker
import yaml
from git.exc import InvalidGitRepositoryError

# Add script directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.team_manage_parent_teams import (
    load_yaml_config,
    find_git_root,
    get_existing_team_directories,
    get_configured_teams,
    delete_team_directory,
    delete_github_team,
    commit_changes,
    main,
)


@pytest.fixture
def mock_repo():
    """Create a mock repository without using spec"""
    with patch("git.Repo") as MockRepo:
        mock_instance = MagicMock()
        mock_instance.working_dir = "/fake/repo/path"
        mock_instance.is_dirty.return_value = True
        mock_instance.untracked_files = []

        # Setup git interface
        mock_instance.git = MagicMock()
        mock_instance.git.add = MagicMock()
        mock_instance.git.rm = MagicMock()

        # Setup remote
        mock_remote = MagicMock()
        mock_remote.name = "origin"
        mock_instance.remotes = [mock_remote]
        mock_instance.remote.return_value = mock_remote

        MockRepo.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_github():
    """Create mock GitHub objects without using spec"""
    with patch("github.Github") as mock_gh:
        mock_gh = MagicMock()
        mock_org = MagicMock()
        mock_team = MagicMock()

        # Setup team methods
        mock_team.name = "test_team"
        mock_team.get_teams.return_value = []
        mock_team.delete = MagicMock()

        # Setup organization methods
        mock_org.get_team_by_slug = MagicMock(return_value=mock_team)

        # Setup GitHub client
        mock_gh.get_organization = MagicMock(return_value=mock_org)

        yield {"github": mock_gh, "org": mock_org, "team": mock_team}


@pytest.fixture
def mock_gh_auth():
    """Mock GitHub authentication and basic operations"""
    with patch("github.Github") as mock_gh:
        # Create mock instances
        mock_instance = MagicMock()
        mock_org = MagicMock()
        mock_team = MagicMock()

        # Setup organization and team chain
        mock_org.get_team_by_slug = MagicMock(return_value=mock_team)
        mock_instance.get_organization = MagicMock(return_value=mock_org)

        # Setup team attributes
        mock_team.name = "team2"
        mock_team.delete = MagicMock()

        # Configure the mock chain
        mock_gh.return_value = mock_instance

        # Store references for assertions
        mock_instance._org = mock_org
        mock_instance._team = mock_team

        yield mock_instance


@pytest.fixture
def sample_config():
    return {"teams": [{"team_name": "team1"}, {"team_name": "team2"}]}


@pytest.fixture
def test_env(monkeypatch: pytest.MonkeyPatch):
    """Setup test environment variables"""
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_ORGANIZATION", "test-org")
    monkeypatch.setenv("GITHUB_REPOSITORY", "test-org/test-repo")
    monkeypatch.setenv("TESTING", "true")


@pytest.fixture
def mock_github_client(mocker: Callable[..., Generator[MockerFixture, None, None]]):
    """Mock GitHub client with proper authentication"""
    mock_gh = mocker.patch("github.Github")
    mock_instance = mocker.MagicMock()
    mock_org = mocker.MagicMock()

    # Setup the mock chain
    mock_instance.get_organization.return_value = mock_org
    mock_gh.return_value = mock_instance

    return {"client": mock_instance, "org": mock_org, "gh": mock_gh}


def test_load_yaml_config(tmp_path: Path):
    """Test loading YAML configuration"""
    config_file = tmp_path / "teams.yml"
    test_config = {"teams": [{"team_name": "test_team"}]}

    with open(config_file, mode="w", encoding="utf-8") as f:
        yaml.dump(test_config, f)

    result = load_yaml_config(config_file)
    assert result == test_config


def test_find_git_root(mock_repo: MagicMock):
    """Test finding Git repository root"""
    with patch("git.Repo") as MockRepo:
        mock_instance = MagicMock()
        mock_instance.working_dir = "/fake/repo/path"
        MockRepo.return_value = mock_instance

        result = find_git_root()
        assert result == Path("/fake/repo/path")


def test_find_git_root_error():
    """Test error handling when Git repository is not found"""
    with patch("git.Repo", side_effect=InvalidGitRepositoryError):
        with pytest.raises(InvalidGitRepositoryError):
            find_git_root()


def test_get_existing_team_directories(tmp_path: Path):
    """Test getting existing team directories"""
    teams_dir = tmp_path / "teams"
    teams_dir.mkdir()
    (teams_dir / "team1").mkdir()
    (teams_dir / "team2").mkdir()

    result = get_existing_team_directories(tmp_path)
    assert set(result) == {"team1", "team2"}


def test_get_configured_teams(tmp_path: Path):
    """Test getting configured teams from YAML"""
    config_file = tmp_path / "teams.yml"
    test_config = {"teams": [{"team_name": "team1"}, {"team_name": "team2"}]}

    with open(config_file, mode="w", encoding="utf-8") as f:
        yaml.dump(test_config, f)

    result = get_configured_teams(config_file)
    assert result == ["team1", "team2"]


def test_delete_team_directory(tmp_path: Path):
    """Test deleting team directory"""
    team_dir = tmp_path / "teams" / "test_team"
    team_dir.mkdir(parents=True)

    result = delete_team_directory(tmp_path, "test_team")

    assert result is True
    assert not team_dir.exists()


def test_delete_github_team(mock_github: dict[str, MagicMock]):
    """Test deleting GitHub team"""
    mock_org = mock_github["org"]
    mock_team = mock_github["team"]

    # Create a mock sub-team
    mock_sub_team = MagicMock()
    mock_sub_team.name = "sub_team"
    mock_sub_team.delete = MagicMock()
    mock_team.get_teams.return_value = [mock_sub_team]

    result = delete_github_team(mock_org, "test_team")

    assert result is True
    mock_org.get_team_by_slug.assert_called_once_with("test_team")
    mock_sub_team.delete.assert_called_once()
    mock_team.delete.assert_called_once()


def test_commit_changes(mock_repo: MagicMock):
    """Test committing changes"""
    repo_root = Path("/fake/repo/path")
    deleted_teams = ["team1", "team2"]

    commit_changes(repo_root, "Test commit", deleted_teams)

    # Verify git operations
    mock_repo.git.add.assert_has_calls([call(update=True), call(".")])
    mock_repo.index.commit.assert_called_once_with("Test commit")
    mock_repo.remote().push.assert_called_once()


def test_main_workflow(test_env: None, mock_gh_auth: MagicMock, tmp_path: Path):
    """Test the main workflow"""
    # Create a new mock for delete_github_team to track its calls
    mock_delete_github = MagicMock(return_value=True)

    # Setup patch configuration
    patches = {
        "Github": MagicMock(return_value=mock_gh_auth),
        "find_git_root": lambda: tmp_path,
        "get_existing_team_directories": lambda x: ["team1", "team2"],
        "get_configured_teams": lambda x: ["team1"],
        "delete_github_team": mock_delete_github,
        "delete_team_directory": MagicMock(return_value=True),
        "commit_changes": MagicMock(),
    }

    with patch.multiple("scripts.team_manage_parent_teams", **patches):
        # Execute main
        main()

        # Verify that delete_github_team was called with correct parameters
        mock_delete_github.assert_called_once_with(mock_gh_auth._org, "team2")

        # Verify that other operations occurred
        patches["delete_team_directory"].assert_called_once()
        patches["commit_changes"].assert_called_once()


def test_main_no_teams_to_remove(mock_gh_auth: MagicMock, tmp_path: Path):
    with (
        patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
        patch.multiple(
            "scripts.team_manage_parent_teams",
            find_git_root=lambda: tmp_path,
            get_existing_team_directories=lambda x: ["team1"],
            get_configured_teams=lambda x: ["team1"],
        ),
    ):
        main()
        mock_gh_auth.get_organization.return_value.get_team_by_slug.assert_not_called()


def test_error_handling_in_main():
    """Test error handling in main function"""
    with patch("scripts.team_manage_parent_teams.find_git_root", side_effect=InvalidGitRepositoryError):
        with pytest.raises(InvalidGitRepositoryError):
            main()
