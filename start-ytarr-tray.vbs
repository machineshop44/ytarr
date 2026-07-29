Set oShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Folder that contains this .vbs (handles spaces in "yt arr app")
root = fso.GetParentFolderName(WScript.ScriptFullName)
backend = root & "\backend"
script = backend & "\tray_app.py"
oShell.CurrentDirectory = backend

q = Chr(34)
pythonw = oShell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe")

If fso.FileExists(pythonw) Then
  ' Always quote both exe and script — path has spaces
  oShell.Run q & pythonw & q & " " & q & script & q, 0, False
Else
  oShell.Run "pyw -3.12 " & q & script & q, 0, False
End If
