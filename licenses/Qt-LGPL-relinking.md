# Qt / PySide6 LGPL replacement information

Game Chat Translator uses the unmodified PySide6 6.9.1, PySide6 Essentials 6.9.1, PySide6 Addons 6.9.1, and Shiboken6 6.9.1 wheels under the LGPL-3.0 option. The installer uses an unpacked one-folder layout and links dynamically to the Qt and Shiboken DLLs under `_internal\PySide6` and `_internal\shiboken6`.

You may replace those DLLs with ABI-compatible modified builds for debugging your modifications:

1. Exit Game Chat Translator completely from its tray menu.
2. Copy the installed application directory to a user-writable working directory.
3. Replace the applicable Qt 6.9 / PySide6 / Shiboken shared libraries in the copied `_internal` directories with your compatible builds, preserving filenames and architecture.
4. Launch `GameChatTranslator.exe` from that copied directory. The installer and application do not verify or restore the shared-library bytes.

Reverse engineering for debugging modifications to the LGPL-covered libraries is not prohibited. Application source and exact build configuration are available at https://github.com/kazoogh/chat-translator. Corresponding Qt/PySide source is available from https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://code.qt.io/cgit/qt/qt5.git/ using the 6.9.1 tags. The accompanying `LGPL-3.0.txt` and `GPL-3.0.txt` contain the complete applicable license terms.
