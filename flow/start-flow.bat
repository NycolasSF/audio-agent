@echo off
rem Sobe o Flow sem janela de console. Para iniciar com o Windows, crie um
rem atalho deste .bat em shell:startup (Win+R -> shell:startup).
cd /d %~dp0
start "Flow" pythonw flow.py
