' SPDX-License-Identifier: AGPL-3.0-or-later
' Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
' Starts Bug Tracker with no window at all and opens it in the browser.
' Double-click this file, or put a shortcut to it on the desktop / in the
' Startup folder (Win+R, shell:startup) to launch it when you log in.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run """" & folder & "\start_bugtracker.bat"" /silent", 0, False
