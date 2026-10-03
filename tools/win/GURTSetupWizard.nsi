; GURTSetupWizard.exe — GURT on Windows, the classic installer way 🧙
; it runs install.ps1 (WSL + gurt inside it + gurt on your PATH + the Start menu), then opens the setup wizard
; build (on Linux too):  tools/win/build-exe.sh [out-dir]   (needs makensis: apt install nsis)
Unicode true
!ifndef VERSION
  !define VERSION "1.0.0"
!endif
!ifndef PS1
  !define PS1 "..\..\install.ps1"
!endif
!ifndef OUTDIR
  !define OUTDIR "."
!endif
!include "MUI2.nsh"
!include "LogicLib.nsh"

Name "GURT ${VERSION}"
Caption "GURT Setup Wizard"
OutFile "${OUTDIR}\GURTSetupWizard.exe"
RequestExecutionLevel user          ; install.ps1 asks for admin itself, only if WSL needs installing
InstallDir "$LOCALAPPDATA\gurt"
ShowInstDetails show
BrandingText "GURT ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "GURT"
VIAddVersionKey "FileDescription" "GURT Setup Wizard"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "MIT license"

!define MUI_ICON "..\..\site\favicon.ico"
!define MUI_UNICON "..\..\site\favicon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "welcome.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "welcome.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "header.bmp"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Welcome to the GURT Setup Wizard"
!define MUI_WELCOMEPAGE_TEXT "This wizard installs GURT ${VERSION}: every Linux distro's packages, running on Windows through WSL.$\r$\n$\r$\nIt will:$\r$\n  • set up WSL + Ubuntu if you don't have it yet (Windows asks for admin)$\r$\n  • install gurt inside WSL$\r$\n  • put a gurt command on your PATH$\r$\n  • add GURT to your Start menu$\r$\n$\r$\nClick Next to continue."
!define MUI_FINISHPAGE_TITLE "GURT is set up"
!define MUI_FINISHPAGE_TEXT "The GURT Setup Wizard opens in its own window to finish up (your look, starter apps, extras).$\r$\n$\r$\nIf WSL was just installed: reboot if Windows asks, open Ubuntu once to make your Linux username, then run GURTSetupWizard.exe again."
!define MUI_FINISHPAGE_LINK "GURT on GitHub"
!define MUI_FINISHPAGE_LINK_LOCATION "https://github.com/clrealy/GURT"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "GURT"
  SetOutPath "$INSTDIR"
  File "/oname=install.ps1" "${PS1}"
  DetailPrint "running the GURT installer (install.ps1)… this takes a minute"
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\install.ps1"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONEXCLAMATION "the GURT installer stopped early (code $0). scroll the details up for why."
    Abort
  ${EndIf}
  WriteUninstaller "$INSTDIR\Uninstall GURT.exe"
  ; Apps & features: so GURT shows up there and can be removed like any app
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GURT" "DisplayName" "GURT"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GURT" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GURT" "Publisher" "GURT"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GURT" "DisplayIcon" "$INSTDIR\gurt.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GURT" "UninstallString" '"$INSTDIR\Uninstall GURT.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GURT" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GURT" "NoRepair" 1
SectionEnd

; removes the Windows side (the gurt command, the Start menu entry). gurt inside WSL stays: remove it there with your distro
Section "Uninstall"
  Delete "$SMPROGRAMS\GURT.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GURT"
  MessageBox MB_ICONINFORMATION "GURT is off Windows. gurt inside WSL is still there; to remove it too, run in WSL: sudo rm /usr/local/bin/gurt"
SectionEnd
