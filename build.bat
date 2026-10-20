@echo off
rem Gera a pasta executavel\CadastroFormaSeg (pronta para copiar para outro PC).
rem Requer Python 3.12 instalado. Rode a partir da raiz do repositorio.
setlocal
cd /d "%~dp0"

if not exist .venv (
    py -3.12 -m venv .venv || python -m venv .venv || goto :erro
)
call .venv\Scripts\activate.bat || goto :erro
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :erro

python -m pytest -q tests || goto :erro

pyinstaller --noconfirm --clean --windowed ^
    --name CadastroFormaSeg ^
    --paths src ^
    --collect-data pdfminer ^
    --collect-all selenium ^
    --collect-submodules keyring ^
    --hidden-import keyring.backends.Windows ^
    main.py || goto :erro

if exist executavel\CadastroFormaSeg rmdir /s /q executavel\CadastroFormaSeg
if not exist executavel mkdir executavel
xcopy /e /i /q dist\CadastroFormaSeg executavel\CadastroFormaSeg >nul || goto :erro
xcopy /e /i /q config executavel\CadastroFormaSeg\config >nul || goto :erro
copy /y LEIA-ME.txt executavel\CadastroFormaSeg\ >nul

echo.
echo Pronto: executavel\CadastroFormaSeg\CadastroFormaSeg.exe
exit /b 0

:erro
echo.
echo ERRO no build. Veja a mensagem acima.
exit /b 1
