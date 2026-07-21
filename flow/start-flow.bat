@echo off
rem Sobe o stack de ditado: motor transcritor (se não estiver no ar) + Flow.
rem Autostart no login: atalho deste .bat em shell:startup.
cd /d %~dp0

rem Motor já ouvindo em 8020? Se não, sobe numa janela minimizada (logs visíveis).
netstat -ano | findstr /c:":8020 " | findstr /c:"LISTENING" >nul
if errorlevel 1 (
  start "Transcritor" /min /d "%~dp0.." python main.py
)

rem O flow.py tem trava de instância única — rodar de novo não duplica.
start "Flow" pythonw flow.py
