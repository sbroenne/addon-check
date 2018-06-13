import os
import xml.etree.ElementTree as ET
import requests
import logging
from kodi_addon_checker import logger
import gzip
from io import BytesIO

from kodi_addon_checker.common import relative_path
from kodi_addon_checker.record import PROBLEM, Record, WARNING, INFORMATION
from kodi_addon_checker.report import Report
from kodi_addon_checker import check_artwork
from kodi_addon_checker import check_old_addon
from kodi_addon_checker import check_dependencies
from kodi_addon_checker import check_entrypoint
from kodi_addon_checker import handle_files
from kodi_addon_checker import check_files

REL_PATH = ""
ROOT_URL = "http://mirrors.kodi.tv/addons/{branch}/addons.xml.gz"
LOGGER = logging.getLogger(__name__)


def start(addon_path, branch_name, all_repo_addons, pr, config=None):
    addon_id = os.path.basename(os.path.normpath(addon_path))
    addon_report = Report(addon_id)
    LOGGER.info("Checking add-on %s" % addon_id)
    addon_report.add(Record(INFORMATION, "Checking add-on %s" % addon_id))

    repo_addons = all_repo_addons[branch_name]
    addon_xml_path = os.path.join(addon_path, "addon.xml")
    parsed_xml = ET.parse(addon_xml_path).getroot()

    global REL_PATH
    # Extract common path from addon paths
    # All paths will be printed relative to this path
    REL_PATH = os.path.split(addon_path[:-1])[0]
    addon_xml = check_files.check_addon_xml(addon_report, addon_path, parsed_xml)

    if addon_xml is not None:
        if len(addon_xml.findall("*//broken")) == 0:
            file_index = handle_files.create_file_index(addon_path)

            check_dependencies.check_addon_dependencies(addon_report, repo_addons, parsed_xml)

            check_files.check_for_invalid_xml_files(addon_report, file_index)

            check_old_addon.check_for_existing_addon(addon_report, addon_path, all_repo_addons, pr)

            check_files.check_for_invalid_json_files(addon_report, file_index)

            check_artwork.check_artwork(addon_report, addon_path, parsed_xml, file_index)

            max_entrypoint_count = config.configs.get(
                "max_entrypoint_count", 15)
            check_entrypoint.check_complex_addon_entrypoint(
                addon_report, addon_path, parsed_xml, max_entrypoint_count)

            if config.is_enabled("check_license_file_exists"):
                # check if license file is existing
                handle_files.addon_file_exists(addon_report, addon_path,
                                               r"^LICENSE\.txt|LICENSE\.md|LICENSE$")

            if config.is_enabled("check_legacy_strings_xml"):
                _check_for_legacy_strings_xml(addon_report, addon_path)

            if config.is_enabled("check_legacy_language_path"):
                check_files.check_for_legacy_language_path(addon_report, addon_path)

            # Kodi 18 Leia + deprecations
            if config.is_enabled("check_kodi_leia_deprecations"):
                _find_blacklisted_strings(addon_report, addon_path,
                                          ["System.HasModalDialog", "StringCompare", "SubString", "IntegerGreaterThan",
                                           "ListItem.ChannelNumber", "ListItem.SubChannelNumber",
                                           "MusicPlayer.ChannelNumber",
                                           "MusicPlayer.SubChannelNumber", "VideoPlayer.ChannelNumber",
                                           "VideoPlayer.SubChannelNumber"],
                                          [], [".py", ".xml"])

            # General blacklist
            _find_blacklisted_strings(addon_report, addon_path, [], [], [])

            check_files.check_file_whitelist(addon_report, file_index, addon_path)
        else:
            addon_report.add(
                Record(INFORMATION, "Addon marked as broken - skipping"))

    return addon_report


def _check_for_legacy_strings_xml(report: Report, addon_path):
    if handle_files.find_file_recursive("strings.xml", addon_path) is not None:
        report.add(
            Record(PROBLEM, "Found strings.xml in folder %s please migrate to strings.po." % relative_path(addon_path)))


def _find_blacklisted_strings(report: Report, addon_path, problem_list, warning_list, whitelisted_file_types):
    for result in handle_files.find_in_file(addon_path, problem_list, whitelisted_file_types):
        report.add(Record(PROBLEM, "Found blacklisted term %s in file %s:%s (%s)"
                          % (result["term"], result["searchfile"], result["linenumber"], result["line"])))

    for result in handle_files.find_in_file(addon_path, warning_list, whitelisted_file_types):
        report.add(Record(WARNING, "Found blacklisted term %s in file %s:%s (%s)"
                          % (result["term"], result["searchfile"], result["linenumber"], result["line"])))


def _get_addons(xml_url):
    """addon.xml for the target Kodi version"""
    try:
        gz_file = requests.get(xml_url, timeout=(10, 10)).content
        with gzip.open(BytesIO(gz_file), 'rb') as xml_file:
            content = xml_file.read()
        tree = ET.fromstring(content)

        return {
            a.get("id"): a.get("version")
            for a in tree.findall("addon")
        }
    except requests.exceptions.ReadTimeout as errrt:
        LOGGER.error(errrt)
    except requests.exceptions.ConnectTimeout as errct:
        LOGGER.error(errct)


def all_repo_addons():
    branches = ['gotham', 'helix', 'isengard', 'jarvis', 'krypton', 'leia']
    repo_addons = {}

    for branch in branches:
        branch_url = ROOT_URL.format(branch=branch)
        repo_addons[branch] = _get_addons(branch_url)

    return repo_addons
