"""Custom exceptions for InfoMentor integration."""


class InfoMentorError(Exception):
	"""Base exception for InfoMentor errors."""
	pass


class InfoMentorAuthError(InfoMentorError):
	"""Authentication failed."""
	pass


class InfoMentorAPIError(InfoMentorError):
	"""API request failed."""
	pass


class InfoMentorConnectionError(InfoMentorError):
	"""Connection to InfoMentor failed."""
	pass


class InfoMentorDataError(InfoMentorError):
	"""Data parsing or validation error."""
	pass 