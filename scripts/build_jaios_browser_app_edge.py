#!/usr/bin/env python3
"""Build a byte-preserving JAIOS Browser /browser/app derivative with current downloads."""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"JAIOS_BROWSER_APP_BUILD_FAIL: {message}")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        fail(f"{label}: expected exactly one match, observed {count}")
    return source.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 4:
        fail("usage: build_jaios_browser_app_edge.py INPUT_HTML RELEASE_JSON OUTPUT_HTML")

    input_path = Path(sys.argv[1])
    release_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3])

    source = input_path.read_text(encoding="utf-8")
    release = json.loads(release_path.read_text(encoding="utf-8"))

    if release.get("schema") != "jaios-browser-web-release/v1":
        fail("release schema mismatch")
    marker = str(release["releaseMarker"])
    downloads = release["downloads"]
    windows = downloads["windows"]
    dmg = downloads["macosDmg"]
    zip_asset = downloads["macosZip"]
    legacy = release["legacy"]

    required_source = (
        legacy["windowsHref"],
        legacy["windowsLabel"],
        legacy["releaseCopy"],
        '<section id="release">',
        '<body>',
    )
    for value in required_source:
        if value not in source:
            fail(f"current production HTML is missing expected source marker: {value}")

    output = replace_once(
        source,
        "<body>",
        f'<body data-jaios-browser-release="{html.escape(marker, quote=True)}">',
        "release marker",
    )

    old_windows_anchor = (
        f'<a class="cta" id="installWindows" href="{legacy["windowsHref"]}" '
        f'download>{legacy["windowsLabel"]}</a>'
    )
    new_desktop_anchors = (
        f'<a class="cta" id="installWindows" href="{html.escape(windows["url"], quote=True)}">'
        f'{html.escape(windows["label"])}</a>'
        f'<a class="cta" id="installMacDmg" href="{html.escape(dmg["url"], quote=True)}">'
        f'{html.escape(dmg["label"])}</a>'
        f'<a class="cta" id="installMacZip" href="{html.escape(zip_asset["url"], quote=True)}">'
        f'{html.escape(zip_asset["label"])}</a>'
    )
    output = replace_once(output, old_windows_anchor, new_desktop_anchors, "desktop download anchors")

    old_launch_note = (
        '<div class="launch-note" id="launchStatus"><b>WINDOWS</b> '
        '導入済みの場合は起動ボタンを使用してください。初回はZIPを展開して INSTALL.cmd を1回実行します。</div>'
    )
    new_launch_note = (
        '<div class="launch-note" id="launchStatus"><b>WINDOWS / macOS 0.6.3</b> '
        'Windows版は公開EXEを1回実行して導入します。macOS版はUniversal DMGまたはZIPを選択してください。'
        'Windows Publisher SigningおよびmacOS Signing / Notarizationは独立したProvider Gateです。</div>'
    )
    output = replace_once(output, old_launch_note, new_launch_note, "launch note")

    old_disclosure = (
        'Public Alpha: Windows 0.5.3 and Mobile Edition include internal search, Reader, '
        'user-initiated JAIOS Intelligence consultation and the initial 12-signal Page Audit. '
        'Native store distribution, signed Windows packaging and benchmark acceptance remain separate qualification tracks.'
    )
    new_disclosure = (
        'Public release: Windows and macOS 0.6.3. The Windows package includes the accepted native '
        'Copy, Cut, Paste, Select All, Undo and Redo repair, including cross-WebContents Copy / Paste. '
        'The published Windows EXE and macOS Universal DMG / ZIP passed exact-byte public readback. '
        'Windows Publisher Signing and macOS Signing / Notarization remain separate provider-controlled gates.'
    )
    output = replace_once(output, old_disclosure, new_disclosure, "release disclosure")

    output = replace_once(
        output,
        '<h2>One explicit installation. Direct launch thereafter.</h2>',
        '<h2>Verified desktop packages. Direct launch after installation.</h2>',
        "release heading",
    )
    output = replace_once(
        output,
        '<article><h3>First installation</h3><p>FIRST INSTALL downloads one clearly named setup file. Opening it once installs the runtime, registers JAIOS Browser and launches the application.</p></article>',
        '<article><h3>Windows installation</h3><p>DOWNLOAD WINDOWS 0.6.3 obtains the accepted public EXE. Opening it once installs the runtime, registers JAIOS Browser and launches the application.</p></article>',
        "Windows installation card",
    )
    old_integrity = (
        '<article><h3>Integrity</h3><p>Application ASAR SHA-256: '
        '510461bc434e7ef12a8cfbf8e9c6f9c2e2067f2f2c561982f0167ec54221a880</p></article>'
    )
    new_integrity = (
        '<article><h3>Published integrity</h3><p>'
        f'Windows SHA-256: {windows["sha256"]}<br>'
        f'macOS DMG SHA-256: {dmg["sha256"]}<br>'
        f'macOS ZIP SHA-256: {zip_asset["sha256"]}</p></article>'
    )
    output = replace_once(output, old_integrity, new_integrity, "integrity card")

    old_release_jp = (
        '公開Webページから未導入のWindowsアプリを無断実行することは行いません。'
        '初回のみWindowsの実行確認を経てセットアップファイルを1回開き、'
        'その後は登録済みJAIOSプロトコルからネイティブブラウザを直接起動します。'
    )
    new_release_jp = (
        'Windows版は受入済み0.6.3 EXE、macOS版はUniversal DMGまたはZIPから取得します。'
        '公開URLから再取得したBinaryは受入済みSHA-256およびSizeと完全一致しています。'
        'Windows導入後は登録済みJAIOSプロトコルからネイティブブラウザを直接起動します。'
    )
    output = replace_once(output, old_release_jp, new_release_jp, "Japanese release copy")

    for legacy_value in (
        legacy["windowsHref"],
        legacy["windowsLabel"],
        legacy["releaseCopy"],
        "JAIOS-Browser-0.5.3-Windows-x64-Bootstrap.zip",
    ):
        if legacy_value in output:
            fail(f"legacy Browser value remains: {legacy_value}")

    for item in (windows, dmg, zip_asset):
        if output.count(item["url"]) != 1:
            fail(f"expected exactly one public download URL: {item['url']}")
        if item["sha256"] not in output:
            fail(f"missing published SHA-256: {item['sha256']}")

    if output.count(f'data-jaios-browser-release="{marker}"') != 1:
        fail("release marker count mismatch")
    if output.count('id="installWindows"') != 1:
        fail("Windows button count mismatch")
    if output.count('id="installMacDmg"') != 1:
        fail("macOS DMG button count mismatch")
    if output.count('id="installMacZip"') != 1:
        fail("macOS ZIP button count mismatch")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    print(
        "JAIOS_BROWSER_APP_BUILD_PASS: "
        f"marker={marker} bytes={len(output.encode('utf-8'))} downloads=3"
    )


if __name__ == "__main__":
    main()
