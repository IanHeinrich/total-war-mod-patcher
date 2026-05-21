; NSIS Installer Script for TW Mod Patcher
; Requires NSIS 3.x with MUI2

!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!include "WinMessages.nsh"
!include "FileFunc.nsh"
!include "WordFunc.nsh"

; --- General ---
!define PRODUCT_NAME "TW Mod Patcher"
!define PRODUCT_EXE "tw-patcher.exe"
!define PRODUCT_GUI_EXE "tw-patcher-gui.exe"
!define PRODUCT_PUBLISHER "TW Mod Patcher"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define PRODUCT_DIR_REGKEY "Software\${PRODUCT_NAME}"

; Version is passed from CI via /DPRODUCT_VERSION=x.y.z
!ifndef PRODUCT_VERSION
  !define PRODUCT_VERSION "0.0.0"
!endif

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "tw-patcher-${PRODUCT_VERSION}-setup.exe"
InstallDir "$PROGRAMFILES\TW Mod Patcher"
InstallDirRegKey HKLM "${PRODUCT_DIR_REGKEY}" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

; --- Variables ---
Var WorkspaceDir
Var WorkspaceDialog
Var WorkspaceDirRequest
Var WorkspaceBrowseBtn
Var GenerateHelpersCheckbox
Var GenerateHelpers
Var AddToPathCheckbox
Var AddToPath
Var StartMenuCheckbox
Var AddStartMenu
Var DesktopCheckbox
Var AddDesktop

; --- MUI Settings ---
!define MUI_ABORTWARNING
!define MUI_ICON "..\..\icons\icon.ico"
!define MUI_UNICON "..\..\icons\icon.ico"

; --- Pages ---
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\..\LICENSE"
Page custom RPFMPageCreate RPFMPageLeave
!insertmacro MUI_PAGE_DIRECTORY
Page custom WorkspacePageCreate WorkspacePageLeave
Page custom OptionsPageCreate OptionsPageLeave
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Uninstaller pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; --- Language ---
!insertmacro MUI_LANGUAGE "English"

; --- RPFM Prerequisite Page ---
Function RPFMPageCreate
  !insertmacro MUI_HEADER_TEXT "Prerequisite: RPFM" "TW Mod Patcher requires RPFM to function."

  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 100% 36u "TW Mod Patcher requires RPFM (Rusted PackFile Manager) to be installed on your system. It is used to read and write Total War pack files."
  Pop $0

  ${NSD_CreateLabel} 0 42u 100% 12u "Download RPFM from:"
  Pop $0

  ${NSD_CreateLink} 0 56u 100% 12u "https://github.com/Frodo45127/rpfm/releases"
  Pop $0
  ${NSD_OnClick} $0 RPFMOpenLink

  ${NSD_CreateLabel} 0 78u 100% 36u "TW Mod Patcher will automatically detect RPFM if it is installed in a standard location (Program Files, AppData, etc). If installed elsewhere, you can set the path in Settings or via 'tw-patcher config set-rpfm <path>'."
  Pop $0

  ${NSD_CreateLabel} 0 120u 100% 12u "Click Next to acknowledge and continue with installation."
  Pop $0

  nsDialogs::Show
FunctionEnd

Function RPFMOpenLink
  ExecShell "open" "https://github.com/Frodo45127/rpfm/releases"
FunctionEnd

Function RPFMPageLeave
  ; No validation needed — this is informational only
FunctionEnd

; --- Workspace Page ---
Function WorkspacePageCreate
  !insertmacro MUI_HEADER_TEXT "Modding Workspace" "Choose the folder for mod development files."

  nsDialogs::Create 1018
  Pop $WorkspaceDialog
  ${If} $WorkspaceDialog == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 100% 24u "Select the folder where mod sources, workspace files, and output packs will be stored:"
  Pop $0

  ; Default to user's Documents folder (not Program Files — avoids permission issues)
  StrCpy $WorkspaceDir "$DOCUMENTS\TW Mod Patcher"

  ${NSD_CreateDirRequest} 0 30u 75% 12u "$WorkspaceDir"
  Pop $WorkspaceDirRequest

  ${NSD_CreateBrowseButton} 78% 29u 20% 14u "Browse..."
  Pop $WorkspaceBrowseBtn
  ${NSD_OnClick} $WorkspaceBrowseBtn WorkspaceBrowse

  ${NSD_CreateLabel} 0 50u 100% 24u "This folder will contain: sources/, workspace/, and output/ subdirectories."
  Pop $0

  ${NSD_CreateCheckbox} 0 80u 100% 12u "Generate AI helper files for modifying DB entries? (modding docs, Copilot/Claude/Cursor instructions)"
  Pop $GenerateHelpersCheckbox
  ${NSD_Check} $GenerateHelpersCheckbox

  ${NSD_CreateLabel} 0 96u 100% 24u "Creates modding_docs/, .github/copilot-instructions.md, CLAUDE.md, and .cursorrules in the workspace."
  Pop $0

  nsDialogs::Show
FunctionEnd

Function WorkspaceBrowse
  nsDialogs::SelectFolderDialog "Select Modding Workspace Folder" "$WorkspaceDir"
  Pop $0
  ${If} $0 != error
    StrCpy $WorkspaceDir $0
    ${NSD_SetText} $WorkspaceDirRequest $WorkspaceDir
  ${EndIf}
FunctionEnd

Function WorkspacePageLeave
  ${NSD_GetText} $WorkspaceDirRequest $WorkspaceDir
  ${NSD_GetState} $GenerateHelpersCheckbox $GenerateHelpers
FunctionEnd

; --- Options Page ---
Function OptionsPageCreate
  !insertmacro MUI_HEADER_TEXT "Options" "Configure additional installation options."

  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}

  ${NSD_CreateCheckbox} 0 0 100% 12u "Add tw-patcher to system PATH (recommended)"
  Pop $AddToPathCheckbox
  ${NSD_Check} $AddToPathCheckbox

  ${NSD_CreateLabel} 0 20u 100% 24u "This allows running 'tw-patcher' from any command prompt or terminal."
  Pop $0

  ${NSD_CreateCheckbox} 0 46u 100% 12u "Create Start Menu shortcut"
  Pop $StartMenuCheckbox
  ${NSD_Check} $StartMenuCheckbox

  ${NSD_CreateCheckbox} 0 66u 100% 12u "Create Desktop shortcut"
  Pop $DesktopCheckbox
  ${NSD_Check} $DesktopCheckbox

  nsDialogs::Show
FunctionEnd

Function OptionsPageLeave
  ${NSD_GetState} $AddToPathCheckbox $AddToPath
  ${NSD_GetState} $StartMenuCheckbox $AddStartMenu
  ${NSD_GetState} $DesktopCheckbox $AddDesktop
FunctionEnd

; --- Helper Functions ---
; StrContains - checks if a string contains a substring
!macro _StrContains ResultVar SearchString FullString
  Push "${FullString}"
  Push "${SearchString}"
  Call StrContains
  Pop "${ResultVar}"
!macroend
!define StrContains '!insertmacro "_StrContains"'

Function StrContains
  Exch $R1 ; search string
  Exch
  Exch $R2 ; full string
  Push $R3
  Push $R4
  Push $R5

  StrLen $R3 $R1
  StrLen $R4 $R2
  StrCpy $R5 0

  ${Do}
    ${If} $R5 > $R4
      StrCpy $R1 ""
      ${Break}
    ${EndIf}
    StrCpy $0 $R2 $R3 $R5
    ${If} $0 == $R1
      ${Break}
    ${EndIf}
    IntOp $R5 $R5 + 1
  ${Loop}

  Pop $R5
  Pop $R4
  Pop $R3
  Pop $R2
  Exch $R1
FunctionEnd

; --- Installation ---
Section "Install"
  SetOutPath "$INSTDIR"

  ; Copy all files from PyInstaller dist
  File /r "..\..\dist\tw-patcher\*.*"

  ; Copy high-res icon for shortcuts
  File "/oname=icon.ico" "..\..\icons\icon.ico"

  ; Create workspace directory
  CreateDirectory "$WorkspaceDir"
  CreateDirectory "$WorkspaceDir\sources"
  CreateDirectory "$WorkspaceDir\workspace"
  CreateDirectory "$WorkspaceDir\output"

  ; Generate AI helper files if selected
  ${If} $GenerateHelpers == 1
    nsExec::ExecToLog '"$INSTDIR\tw-patcher.exe" scaffold --target "$WorkspaceDir"'
  ${EndIf}

  ; Write config with workspace path (backslashes must be escaped for JSON)
  CreateDirectory "$LOCALAPPDATA\tw-patcher"
  StrCpy $1 $WorkspaceDir
  ${WordReplace} $1 "\" "\\" "+" $1
  FileOpen $0 "$LOCALAPPDATA\tw-patcher\config.json" w
  ${If} $0 != ""
    FileWrite $0 '{$\r$\n'
    FileWrite $0 '  "modding_root": "$1"$\r$\n'
    FileWrite $0 '}$\r$\n'
    FileClose $0
  ${EndIf}

  ; Add to PATH if selected
  ${If} $AddToPath == 1
    ; Read current system PATH
    ReadRegStr $0 HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path"
    ; Append install dir (always safe — uninstaller removes it)
    ${If} $0 == ""
      WriteRegExpandStr HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path" "$INSTDIR"
    ${Else}
      ; Check if already in PATH
      ${StrContains} $1 "$INSTDIR" $0
      ${If} $1 == ""
        WriteRegExpandStr HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path" "$0;$INSTDIR"
      ${EndIf}
    ${EndIf}
    ; Broadcast environment change to all windows
    SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
  ${EndIf}

  ; Create Start Menu shortcuts (if selected)
  ${If} $AddStartMenu == 1
    CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\TW Mod Patcher.lnk" "$INSTDIR\${PRODUCT_GUI_EXE}" "" "$INSTDIR\icon.ico" 0
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\TW Mod Patcher (CLI).lnk" "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\icon.ico" 0
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall.lnk" "$INSTDIR\uninstall.exe"
  ${EndIf}

  ; Create Desktop shortcut (if selected)
  ${If} $AddDesktop == 1
    CreateShortCut "$DESKTOP\TW Mod Patcher.lnk" "$INSTDIR\${PRODUCT_GUI_EXE}" "" "$INSTDIR\icon.ico" 0
  ${EndIf}

  ; Write uninstaller
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Write registry keys for Add/Remove Programs
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\icon.ico"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "InstallDir" "$INSTDIR"

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

; --- Uninstallation ---
Section "Uninstall"
  ; Remove from PATH
  ReadRegStr $0 HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path"
  ${If} $0 != ""
    ; Remove our entry from PATH
    ${WordReplace} $0 ";$INSTDIR" "" "+" $1
    ${WordReplace} $1 "$INSTDIR;" "" "+" $2
    ${WordReplace} $2 "$INSTDIR" "" "+" $3
    WriteRegExpandStr HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path" "$3"
    SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
  ${EndIf}

  ; Remove shortcuts
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\TW Mod Patcher.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\TW Mod Patcher (CLI).lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall.lnk"
  RMDir "$SMPROGRAMS\${PRODUCT_NAME}"
  Delete "$DESKTOP\TW Mod Patcher.lnk"

  ; Remove files
  RMDir /r "$INSTDIR"

  ; Remove registry keys
  DeleteRegKey HKLM "${PRODUCT_UNINST_KEY}"
  DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
SectionEnd
