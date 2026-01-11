"""Exceptions for Duke Energy API client."""


class DukeEnergyError(Exception):
    """Base exception for Duke Energy API errors."""


class DukeEnergyAuthError(DukeEnergyError):
    """Exception raised when authentication fails."""


class DukeEnergyTokenExpiredError(DukeEnergyAuthError):
    """Exception raised when the access token has expired."""
