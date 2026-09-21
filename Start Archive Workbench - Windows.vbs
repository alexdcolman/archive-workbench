Option Explicit
Dim shell, fso, base, temp, logPath, command, rc, content, stream
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
temp = shell.ExpandEnvironmentStrings("%TEMP%")
logPath = fso.BuildPath(temp, "archive_workbench_start_" & Replace(CStr(Timer), ".", "_") & ".log")
shell.Environment("PROCESS")("AW_GUI_LAUNCH") = "1"
command = "cmd.exe /d /c """ & fso.BuildPath(base, "Start Archive Workbench - Windows.bat") & """ >""" & logPath & """ 2>&1"
rc = shell.Run(command, 0, True)
If rc <> 0 Then
  content = "No se pudo iniciar Archive Workbench."
  If fso.FileExists(logPath) Then
    Set stream = fso.OpenTextFile(logPath, 1, False)
    content = content & vbCrLf & vbCrLf & stream.ReadAll
    stream.Close
  End If
  MsgBox content, 16, "Archive Workbench"
End If
If fso.FileExists(logPath) Then fso.DeleteFile logPath, True
