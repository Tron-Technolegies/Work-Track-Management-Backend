' WorkTrack Silent Agent Launcher
' Runs desktop_agent.py with no visible console window.
Option Explicit
Dim oShell, oFSO, sDir, sPython, sScript, sCmd
Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")
sDir = oFSO.GetParentFolderName(WScript.ScriptFullName)
sPython = sDir & "\venv\Scripts\pythonw.exe"
If Not oFSO.FileExists(sPython) Then
    sPython = "pythonw"
End If
sScript = sDir & "\desktop_agent.py"
If Not oFSO.FileExists(sScript) Then
    MsgBox "WorkTrack Agent not found at: " & sScript, 16, "WorkTrack Error"
    WScript.Quit 1
End If
sCmd = """" & sPython & """ """ & sScript & """"
oShell.Run sCmd, 0, False
WScript.Quit 0
