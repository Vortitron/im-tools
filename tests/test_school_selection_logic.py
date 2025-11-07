#!/usr/bin/env python3
"""Tests for the improved school selection heuristics."""

import sys
import types
import importlib.util
from pathlib import Path


# Provide lightweight stubs so we can import auth.py without installing aiohttp.
aiohttp_stub = types.ModuleType("aiohttp")


class _ClientSession:  # pragma: no cover - stub
	pass


class _ClientTimeout:  # pragma: no cover - stub
	def __init__(self, *args, **kwargs):
		pass


class _ClientError(Exception):  # pragma: no cover - stub
	pass


class _ContentTypeError(Exception):  # pragma: no cover - stub
	pass


aiohttp_stub.ClientSession = _ClientSession
aiohttp_stub.ClientTimeout = _ClientTimeout
aiohttp_stub.ClientError = _ClientError
aiohttp_stub.ContentTypeError = _ContentTypeError
sys.modules.setdefault("aiohttp", aiohttp_stub)


voluptuous_stub = types.ModuleType("voluptuous")
sys.modules.setdefault("voluptuous", voluptuous_stub)


BASE_DIR = Path(__file__).resolve().parent.parent
PACKAGE_DIR = BASE_DIR / "custom_components" / "infomentor"
LIB_DIR = PACKAGE_DIR / "infomentor"


infomentor_pkg = types.ModuleType("infomentor")
infomentor_pkg.__path__ = [str(PACKAGE_DIR)]
sys.modules.setdefault("infomentor", infomentor_pkg)


infomentor_sub_pkg = types.ModuleType("infomentor.infomentor")
infomentor_sub_pkg.__path__ = [str(LIB_DIR)]
sys.modules.setdefault("infomentor.infomentor", infomentor_sub_pkg)


auth_spec = importlib.util.spec_from_file_location("infomentor.infomentor.auth", LIB_DIR / "auth.py")
auth_module = importlib.util.module_from_spec(auth_spec)
sys.modules["infomentor.infomentor.auth"] = auth_module
assert auth_spec and auth_spec.loader
auth_spec.loader.exec_module(auth_module)


_choose_best_school_option = auth_module._choose_best_school_option


def test_prefers_general_option_when_no_clues():
	"""The generic InfoMentor option should win when no other clues exist."""
	options = [
		("Avesta kommun, elever", "https://sso.infomentor.se/login.ashx?idp=avesta_stu"),
		("Ovrigt InfoMentor SSO Test", "https://ims-grandid-api.infomentor.se/Login/initial?communeId=0000012345"),
	]
	selected, scored = _choose_best_school_option(options, None, None, None)
	assert selected == options[1]
	assert scored[0][0] == options[1][0]


def test_respects_stored_url_even_if_lower_score():
	"""A stored school URL must take precedence over heuristic scoring."""
	options = [
		("Avesta kommun, elever", "https://sso.infomentor.se/login.ashx?idp=avesta_stu"),
		("Ovrigt InfoMentor SSO Test", "https://ims-grandid-api.infomentor.se/Login/initial?communeId=0000012345"),
	]
	selected, scored = _choose_best_school_option(options, options[0][1], None, None)
	assert selected == options[0]
	assert scored[0][0] == options[0][0]


def test_domain_clue_prioritises_matching_school():
	"""A domain hint in the username should prioritise the matching municipality."""
	options = [
		("Goteborgs Stad, elever", "https://sso.infomentor.se/login.ashx?idp=goteborg_stu"),
		("Ovrigt InfoMentor SSO Test", "https://ims-grandid-api.infomentor.se/Login/initial?communeId=0000012345"),
	]
	selected, scored = _choose_best_school_option(options, None, None, "parent@goteborg.se")
	assert selected == options[0]
	assert scored[0][0] == options[0][0]

