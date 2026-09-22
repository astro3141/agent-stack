# Keep the system from idle-sleeping while this process runs (SetThreadExecutionState).
# No power settings are changed. Stop the process and the request disappears; the display
# may still turn off, and lid close / manual sleep still sleep.
#   start:  Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','D:\Work\poc-278\tools\keep-awake.ps1'
#   stop:   Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object CommandLine -like '*keep-awake.ps1*' | ForEach-Object { Stop-Process -Id $_.ProcessId }
Add-Type -Namespace KeepAwake -Name Native -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);
'@
$ES_CONTINUOUS      = [uint32]'0x80000000'
$ES_SYSTEM_REQUIRED = [uint32]'0x00000001'
# The request belongs to the calling thread, so set it and keep this thread alive.
while ($true) {
    [void][KeepAwake.Native]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
    Start-Sleep -Seconds 60
}
