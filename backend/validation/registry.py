"""Configurable registry of known IBM utilities, aliases, and user-defined programs."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "programs_config.json"

DEFAULT_KNOWN_UTILITIES = [
    "SORT",
    "ICEMAN",
    "IEFBR14",
    "IEBGENER",
    "IDCAMS",
    "IEBCOPY",
    "IEBUPDTE",
    "IKJEFT01",
    "IKJEFT1A",
    "IKJEFT1B",
]

DEFAULT_ALIASES = {
    "DFSORT": "SORT",
    "SYNCSORT": "SORT",
    "ICETOOL": "SORT",
}


class ProgramRegistry:
    """Registry managing known IBM utilities, aliases, user programs, and typo detection."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.known_utilities: Set[str] = set()
        self.aliases: Dict[str, str] = {}
        self.user_programs: Set[str] = set()
        self.fuzzy_threshold: float = 0.7
        self.max_suggestions: int = 1
        self.load_config()

    def load_config(self, custom_path: Optional[Path] = None) -> None:
        path = custom_path or self.config_path
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.known_utilities = {
                    u.strip().upper() for u in data.get("known_utilities", []) if u.strip()
                }
                self.aliases = {
                    k.strip().upper(): v.strip().upper()
                    for k, v in data.get("aliases", {}).items()
                    if k.strip() and v.strip()
                }
                self.user_programs = {
                    p.strip().upper() for p in data.get("user_programs", []) if p.strip()
                }
                site_rules = data.get("site_rules", {})
                self.fuzzy_threshold = float(site_rules.get("fuzzy_threshold", 0.7))
                self.max_suggestions = int(site_rules.get("max_suggestions", 1))
                return
            except Exception:
                pass  # Fall back to built-in defaults

        # Fallback defaults
        self.known_utilities = set(DEFAULT_KNOWN_UTILITIES)
        self.aliases = dict(DEFAULT_ALIASES)
        self.user_programs = set()
        self.fuzzy_threshold = 0.7
        self.max_suggestions = 1

    def is_known_utility(self, name: str) -> bool:
        """Returns True if the program is in known utilities or known utility aliases."""
        norm = name.strip().upper()
        return norm in self.known_utilities or norm in self.aliases

    def is_user_program(self, name: str) -> bool:
        """Returns True if the program is registered in user-defined programs."""
        return name.strip().upper() in self.user_programs

    def is_known_program(self, name: str) -> bool:
        """Returns True if program is known (IBM utility, alias, or user-defined)."""
        norm = name.strip().upper()
        return norm in self.known_utilities or norm in self.aliases or norm in self.user_programs

    def get_canonical_utility(self, name: str) -> str:
        """Resolves aliases to canonical utility names (e.g., DFSORT, ICEMAN -> SORT)."""
        norm = name.strip().upper()
        return self.aliases.get(norm, norm)

    def get_candidate_programs(self) -> List[str]:
        """Returns sorted list of all known program names and aliases for candidate matching."""
        pool: Set[str] = set(self.known_utilities)
        pool.update(self.aliases.keys())
        pool.update(self.user_programs)
        return sorted(pool)

    def find_close_program_match(
        self, name: str, cutoff: Optional[float] = None
    ) -> Optional[str]:
        """Finds closest known program match if similarity is sufficiently high, else None.

        If the program is already in the registry, returns None (no typo).
        """
        if not name or not name.strip():
            return None
        norm = name.strip().upper()

        # If already known, it's not a typo
        if self.is_known_program(norm):
            return None

        threshold = cutoff if cutoff is not None else self.fuzzy_threshold
        candidates = self.get_candidate_programs()

        matches = difflib.get_close_matches(
            norm, candidates, n=self.max_suggestions, cutoff=threshold
        )
        if matches:
            best_match = matches[0]
            # Ensure not suggesting identical name (safety check)
            if best_match != norm:
                return best_match

        return None

    def register_user_program(self, name: str) -> None:
        """Registers a custom/site-specific program name at runtime."""
        if name and name.strip():
            self.user_programs.add(name.strip().upper())

    def unregister_user_program(self, name: str) -> None:
        """Unregisters a custom program name."""
        norm = name.strip().upper()
        self.user_programs.discard(norm)

    def reset_registry(self) -> None:
        """Resets registry back to config file state."""
        self.load_config()


# Global default registry instance
default_registry = ProgramRegistry()


def is_known_program(name: str) -> bool:
    return default_registry.is_known_program(name)


def is_known_utility(name: str) -> bool:
    return default_registry.is_known_utility(name)


def get_canonical_utility(name: str) -> str:
    return default_registry.get_canonical_utility(name)


def find_close_program_match(name: str, cutoff: Optional[float] = None) -> Optional[str]:
    return default_registry.find_close_program_match(name, cutoff=cutoff)


def register_user_program(name: str) -> None:
    default_registry.register_user_program(name)


def unregister_user_program(name: str) -> None:
    default_registry.unregister_user_program(name)


def reset_registry() -> None:
    default_registry.reset_registry()
