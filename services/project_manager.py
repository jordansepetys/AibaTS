import os
from pathlib import Path
from typing import Optional
from loguru import logger


class ProjectManager:
    """Manages project folder structure and wiki initialization."""
    
    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir)
        self.projects_dir = self.base_dir / "projects"
    
    def ensure_project_structure(self, project_name: str) -> Path:
        """
        Ensure project folder structure exists for the given project.
        
        Creates:
        - ./projects/{ProjectName}/
        - ./projects/{ProjectName}/wiki.md
        - ./projects/{ProjectName}/meetings/
        
        Args:
            project_name: Name of the project
            
        Returns:
            Path to the project directory
        """
        # Sanitize project name for filesystem
        safe_project_name = self._sanitize_project_name(project_name)
        project_dir = self.projects_dir / safe_project_name
        
        # Create project directory
        project_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured project directory: {project_dir}")
        
        # Create meetings subdirectory
        meetings_dir = project_dir / "meetings"
        meetings_dir.mkdir(exist_ok=True)
        logger.debug(f"Ensured meetings directory: {meetings_dir}")
        
        # Create or verify wiki.md exists
        wiki_path = project_dir / "wiki.md"
        if not wiki_path.exists():
            self._initialize_wiki(wiki_path, project_name)
            logger.info(f"Created new project wiki: {wiki_path}")
        else:
            logger.debug(f"Project wiki already exists: {wiki_path}")
        
        return project_dir
    
    def get_project_wiki_path(self, project_name: str) -> Path:
        """Get the path to a project's wiki.md file."""
        safe_project_name = self._sanitize_project_name(project_name)
        return self.projects_dir / safe_project_name / "wiki.md"
    
    def get_project_meetings_dir(self, project_name: str) -> Path:
        """Get the path to a project's meetings directory."""
        safe_project_name = self._sanitize_project_name(project_name)
        return self.projects_dir / safe_project_name / "meetings"
    
    def get_project_dir(self, project_name: str) -> Path:
        """Get the path to a project's root directory."""
        safe_project_name = self._sanitize_project_name(project_name)
        return self.projects_dir / safe_project_name
    
    def list_projects(self) -> list[str]:
        """List all existing projects."""
        if not self.projects_dir.exists():
            return []
        
        projects = []
        for item in self.projects_dir.iterdir():
            if item.is_dir() and (item / "wiki.md").exists():
                projects.append(item.name)
        
        return sorted(projects)
    
    def project_exists(self, project_name: str) -> bool:
        """Check if a project already exists."""
        safe_project_name = self._sanitize_project_name(project_name)
        project_dir = self.projects_dir / safe_project_name
        return project_dir.exists() and (project_dir / "wiki.md").exists()
    
    def _sanitize_project_name(self, project_name: str) -> str:
        """Sanitize project name for use as a directory name."""
        # Remove or replace invalid characters for filesystem
        invalid_chars = '<>:"/\\|?*'
        sanitized = project_name
        for char in invalid_chars:
            sanitized = sanitized.replace(char, '_')
        
        # Remove leading/trailing whitespace and dots
        sanitized = sanitized.strip('. ')
        
        # Ensure it's not empty
        if not sanitized:
            sanitized = "Project"
        
        return sanitized
    
    def _initialize_wiki(self, wiki_path: Path, project_name: str) -> None:
        """Initialize a new wiki.md file with the template header."""
        template = f"""# {project_name} Project Wiki

## Meeting History

---
"""
        wiki_path.write_text(template, encoding="utf-8")


# Global instance
project_manager = ProjectManager()
