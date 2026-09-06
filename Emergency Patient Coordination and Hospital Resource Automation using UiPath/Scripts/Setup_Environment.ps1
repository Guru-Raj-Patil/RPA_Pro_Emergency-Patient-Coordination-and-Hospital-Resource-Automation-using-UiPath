# =============================================================================
# Setup_Environment.ps1
# Emergency Patient Coordination – UiPath RPA Project Environment Setup
#
# This script:
#   1. Creates the full project folder structure
#   2. Downloads sqlite3.exe if not present
#   3. Creates HospitalDB.db from InitDB.sql
#   4. Copies test SQL scripts to Scripts/
#   5. Creates placeholder patient documents (PDF-named text files)
#   6. Creates Config.xlsx using Excel COM
#   7. Creates PatientInput.xlsx using Excel COM
#   8. Validates the setup
#
# Run from PowerShell as the project root:
#   Set-Location "c:\Users\Gurupatil\Documents\UiPath\Emergency Patient Coordination and Hospital Resource Automation using UiPath"
#   .\Scripts\Setup_Environment.ps1
# =============================================================================

param(
    [switch]$SkipExcel   # Pass -SkipExcel if Microsoft Excel is not installed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Step { param($msg) Write-Host "`n[STEP] $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "  [OK] $msg"   -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  [!!] $msg"   -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host " [ERR] $msg"   -ForegroundColor Red }

# ---------------------------------------------------------------------------
# Resolve project root (script lives in Scripts\ so parent is root)
# ---------------------------------------------------------------------------
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$ProjectRoot\project.json")) {
    $ProjectRoot = $PSScriptRoot   # fallback if run from root directly
}
Write-Ok "Project root: $ProjectRoot"

# ---------------------------------------------------------------------------
# STEP 1 – Folder structure
# ---------------------------------------------------------------------------
Write-Step "Creating folder structure"

$Folders = @(
    "Data",
    "Scripts",
    "Framework",
    "Workflows",
    "Docs",
    "Patients\P1024",
    "Patients\P1025",
    "Patients\P1026",
    "Patients\P1027",
    "Patients\P1028",
    "Patients\P1029",
    "Patients\P1030",
    "Patients\P1031"
)

foreach ($f in $Folders) {
    $fullPath = Join-Path $ProjectRoot $f
    if (-not (Test-Path $fullPath)) {
        New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
        Write-Ok "Created: $f"
    } else {
        Write-Warn "Exists:  $f"
    }
}

# ---------------------------------------------------------------------------
# STEP 2 – Copy SQL scripts to Scripts/
# ---------------------------------------------------------------------------
Write-Step "Copying SQL scripts to Scripts/"

$SqlFiles = @(
    "InitDB.sql",
    "TestSetup_T3_NoBed.sql",
    "TestSetup_T4_NoVent.sql",
    "TestSetup_T5_LowBlood.sql",
    "TestReset.sql"
)

$ScratchDir = "$env:USERPROFILE\.gemini\antigravity-ide\brain\90f607e5-afba-40cb-8a19-151a2607ce8e\scratch"
foreach ($sf in $SqlFiles) {
    $src  = Join-Path $ScratchDir $sf
    $dest = Join-Path $ProjectRoot "Scripts\$sf"
    if (Test-Path $src) {
        Copy-Item $src $dest -Force
        Write-Ok "Copied: $sf"
    } else {
        Write-Warn "Source not found (will use inline): $sf"
    }
}

# ---------------------------------------------------------------------------
# STEP 3 – Download sqlite3.exe if missing
# ---------------------------------------------------------------------------
Write-Step "Checking sqlite3.exe"

$SqliteBin = Join-Path $ProjectRoot "Scripts\sqlite3.exe"

if (-not (Test-Path $SqliteBin)) {
    Write-Warn "sqlite3.exe not found – downloading from GitHub releases..."
    try {
        $zipUrl  = "https://github.com/nicowillis/sqlite-tools-win32-x86/raw/main/sqlite3.exe"
        # Primary: official SQLite download page
        $zipUrl  = "https://www.sqlite.org/2024/sqlite-tools-win32-x86-3460000.zip"
        $zipDest = Join-Path $env:TEMP "sqlite_tools.zip"
        $extractDir = Join-Path $env:TEMP "sqlite_tools"

        Invoke-WebRequest -Uri $zipUrl -OutFile $zipDest -UseBasicParsing -TimeoutSec 60
        Expand-Archive -Path $zipDest -DestinationPath $extractDir -Force
        $exe = Get-ChildItem -Path $extractDir -Filter "sqlite3.exe" -Recurse | Select-Object -First 1
        if ($exe) {
            Copy-Item $exe.FullName $SqliteBin -Force
            Write-Ok "sqlite3.exe downloaded and placed at Scripts\"
        } else {
            throw "sqlite3.exe not found in zip"
        }
    } catch {
        Write-Warn "Auto-download failed: $_"
        Write-Warn "Please download sqlite3.exe from https://sqlite.org/download.html"
        Write-Warn "and place it at: $SqliteBin"
        Write-Warn "Then re-run this script."
        # Continue anyway – DB creation will fail gracefully below
    }
} else {
    Write-Ok "sqlite3.exe found"
}

# ---------------------------------------------------------------------------
# STEP 4 – Create HospitalDB.db
# ---------------------------------------------------------------------------
Write-Step "Creating HospitalDB.db"

$DbPath  = Join-Path $ProjectRoot "Data\HospitalDB.db"
$SqlPath = Join-Path $ProjectRoot "Scripts\InitDB.sql"

if (-not (Test-Path $SqlPath)) {
    Write-Fail "InitDB.sql not found at $SqlPath – cannot create database"
} elseif (-not (Test-Path $SqliteBin)) {
    Write-Fail "sqlite3.exe not found – cannot create database"
} else {
    # Remove existing DB for clean creation
    if (Test-Path $DbPath) {
        Remove-Item $DbPath -Force
        Write-Warn "Removed existing HospitalDB.db"
    }

    $result = & $SqliteBin $DbPath ".read `"$SqlPath`"" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "HospitalDB.db created successfully"
        # Quick row-count verification
        $counts = & $SqliteBin $DbPath "SELECT name, (SELECT COUNT(*) FROM sqlite_master WHERE name=m.name) FROM sqlite_master m WHERE type='table' ORDER BY name;" 2>&1
        Write-Ok "Database tables created"
    } else {
        Write-Fail "sqlite3 returned error: $result"
    }
}

# ---------------------------------------------------------------------------
# STEP 5 – Placeholder patient documents
# ---------------------------------------------------------------------------
Write-Step "Creating placeholder patient documents"

# Document types and patient IDs
$Patients = @{
    'P1024' = @('ID_Proof','Insurance','Consent_Form','Medical_Report')  # all present
    'P1025' = @('ID_Proof','Insurance','Consent_Form')                   # Medical_Report missing (T2)
    'P1026' = @('ID_Proof','Insurance','Consent_Form','Medical_Report')
    'P1027' = @('ID_Proof','Insurance','Consent_Form','Medical_Report')
    'P1028' = @('ID_Proof','Insurance','Consent_Form','Medical_Report')
    'P1029' = @('ID_Proof','Insurance','Consent_Form','Medical_Report')
    'P1030' = @('ID_Proof','Insurance','Consent_Form','Medical_Report')
    'P1031' = @('ID_Proof','Insurance','Consent_Form','Medical_Report')
}

$DocContent = @{
    'ID_Proof'      = "HOSPITAL PATIENT IDENTITY PROOF`n============================`nThis document serves as patient identity verification.`nIssued by: City General Hospital`nDocument Type: ID_Proof`nVerification Status: VALID`n"
    'Insurance'     = "HEALTH INSURANCE CERTIFICATE`n============================`nThis document confirms active health insurance coverage.`nIssued by: National Health Insurance Corp`nDocument Type: Insurance`nVerification Status: VALID`n"
    'Consent_Form'  = "PATIENT CONSENT FORM`n============================`nI hereby consent to hospital admission and necessary administrative procedures.`nDocument Type: Consent_Form`nVerification Status: VALID`n"
    'Medical_Report'= "MEDICAL REFERRAL REPORT`n============================`nThis document contains the referring physician's notes for emergency admission.`nDocument Type: Medical_Report`nVerification Status: VALID`n"
}

foreach ($pid in $Patients.Keys) {
    $patientDir = Join-Path $ProjectRoot "Patients\$pid"
    foreach ($docType in $Patients[$pid]) {
        $filePath = Join-Path $patientDir "$docType.pdf"
        if (-not (Test-Path $filePath)) {
            $content = $DocContent[$docType]
            $content += "`nPatient ID: $pid`nGenerated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n"
            # Write as UTF-8 text (placeholder – mimics PDF presence for file-based verification)
            [System.IO.File]::WriteAllText($filePath, $content, [System.Text.Encoding]::UTF8)
            Write-Ok "Created: Patients\$pid\$docType.pdf"
        } else {
            Write-Warn "Exists:  Patients\$pid\$docType.pdf"
        }
    }
}

# ---------------------------------------------------------------------------
# STEP 6 – Config.xlsx
# ---------------------------------------------------------------------------
Write-Step "Creating Config.xlsx"

$ConfigPath = Join-Path $ProjectRoot "Data\Config.xlsx"

if ($SkipExcel) {
    Write-Warn "-SkipExcel flag set. Skipping Config.xlsx creation."
} else {
    try {
        $Excel = New-Object -ComObject Excel.Application
        $Excel.Visible = $false
        $Excel.DisplayAlerts = $false

        $Wb = $Excel.Workbooks.Add()
        $Ws = $Wb.Worksheets.Item(1)
        $Ws.Name = "Settings"

        # Headers
        $Ws.Cells.Item(1,1).Value2 = "Key"
        $Ws.Cells.Item(1,2).Value2 = "Value"
        $Ws.Cells.Item(1,3).Value2 = "Description"
        $Ws.Cells.Item(1,1).Font.Bold = $true
        $Ws.Cells.Item(1,2).Font.Bold = $true
        $Ws.Cells.Item(1,3).Font.Bold = $true

        $Settings = @(
            @("HospitalName",         "City General Hospital",           "Name of the hospital"),
            @("DatabasePath",         "Data\HospitalDB.db",              "Path to SQLite DB relative to project root"),
            @("PatientDocumentRoot",  "Patients",                        "Folder containing patient document subfolders"),
            @("RequiredDocuments",    "ID_Proof,Insurance,Consent_Form,Medical_Report", "Comma-separated required document types"),
            @("BloodMinThresholdDefault","3",                            "Default minimum blood threshold if not in DB"),
            @("StaffEmailTo",         "admin@hospital.local",            "Primary notification recipient"),
            @("StaffEmailCC",         "duty.doctor@hospital.local",      "CC notification recipient"),
            @("SMTPServer",           "smtp.hospital.local",             "SMTP server hostname"),
            @("SMTPPort",             "587",                             "SMTP port"),
            @("SMTPFrom",             "rpa-bot@hospital.local",          "Sender email address"),
            @("RetryCount",           "3",                               "Number of retries for system exceptions"),
            @("RetryTimeout_sec",     "5",                               "Seconds between retries"),
            @("UseQueue",             "False",                           "True=Orchestrator Queue, False=Excel input"),
            @("UseActionCenter",      "False",                           "True=Action Center HITL, False=Local Form"),
            @("OrchestratorQueueName","EmergencyQueue",                  "Orchestrator queue name"),
            @("ActionCenterCatalog",  "EmergencyApprovals",              "Action Center task catalog name"),
            @("LogLevel",             "Info",                            "Logging verbosity: Info / Warn / Error"),
            @("CaseIdPrefix",         "ER",                              "Prefix for generated Case IDs"),
            @("EmailSimulated",       "True",                            "True=write HTML file instead of sending email"),
            @("EmailOutputFolder",    "Data\Notifications",              "Folder for simulated email HTML files")
        )

        $row = 2
        foreach ($s in $Settings) {
            $Ws.Cells.Item($row,1).Value2 = $s[0]
            $Ws.Cells.Item($row,2).Value2 = $s[1]
            $Ws.Cells.Item($row,3).Value2 = $s[2]
            $row++
        }

        # Auto-fit columns
        $Ws.Columns.Item("A:C").AutoFit() | Out-Null

        # Add table formatting
        $Range = $Ws.Range("A1:C$($row-1)")
        $Table = $Ws.ListObjects.Add(1, $Range, $null, 1)
        $Table.Name = "ConfigSettings"
        $Table.TableStyle = "TableStyleMedium2"

        if (Test-Path $ConfigPath) { Remove-Item $ConfigPath -Force }
        $Wb.SaveAs($ConfigPath, 51)  # 51 = xlsx
        $Wb.Close($false)
        $Excel.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($Excel) | Out-Null
        Write-Ok "Config.xlsx created at Data\"
    } catch {
        Write-Warn "Excel COM failed: $_"
        Write-Warn "Config.xlsx not created. Please create it manually using the structure in the implementation plan."
    }
}

# ---------------------------------------------------------------------------
# STEP 7 – PatientInput.xlsx
# ---------------------------------------------------------------------------
Write-Step "Creating PatientInput.xlsx"

$InputPath = Join-Path $ProjectRoot "Data\PatientInput.xlsx"

if ($SkipExcel) {
    Write-Warn "-SkipExcel flag set. Skipping PatientInput.xlsx creation."
} else {
    try {
        $Excel = New-Object -ComObject Excel.Application
        $Excel.Visible = $false
        $Excel.DisplayAlerts = $false

        $Wb = $Excel.Workbooks.Add()
        $Ws = $Wb.Worksheets.Item(1)
        $Ws.Name = "EmergencyRequests"

        # Headers
        $Headers = @("PatientId","Name","Age","Gender","EmergencyType","RequiredDepartment","VentilatorRequired","BloodGroup","BloodUnits","ProcessStatus","CaseId","Notes")
        for ($c = 1; $c -le $Headers.Count; $c++) {
            $Ws.Cells.Item(1,$c).Value2 = $Headers[$c-1]
            $Ws.Cells.Item(1,$c).Font.Bold = $true
        }

        # Patient data (ProcessStatus=Pending means not yet processed by bot)
        $Patients = @(
            @("P1024","Rahul Kumar",  54,"Male",  "Critical","ICU",        "Yes","O-",  4,"Pending","",""),
            @("P1025","Ananya Singh", 32,"Female","Urgent",  "ICU",        "No", "A+",  2,"Pending","",""),
            @("P1026","Mohan Das",    67,"Male",  "Critical","ICU",        "Yes","B+",  3,"Pending","",""),
            @("P1027","Priya Sharma", 45,"Female","Critical","ICU",        "Yes","AB+", 2,"Pending","",""),
            @("P1028","Arun Mehta",   29,"Male",  "Critical","ICU",        "Yes","O-", 10,"Pending","",""),
            @("P1029","Kavitha Nair", 38,"Female","Standard","General",    "No", "B-",  2,"Pending","",""),
            @("P1030","Suresh Patel", 61,"Male",  "Urgent",  "General",    "No", "A-",  1,"Pending","",""),
            @("P1031","Deepa Reddy",  55,"Female","Critical","Cardiology",  "No", "AB-", 1,"Pending","","")
        )

        $row = 2
        foreach ($p in $Patients) {
            for ($c = 1; $c -le $p.Count; $c++) {
                $Ws.Cells.Item($row,$c).Value2 = $p[$c-1]
            }
            $row++
        }

        # Auto-fit
        $Ws.Columns.Item("A:L").AutoFit() | Out-Null

        # Table formatting
        $Range = $Ws.Range("A1:L$($row-1)")
        $Table = $Ws.ListObjects.Add(1, $Range, $null, 1)
        $Table.Name = "EmergencyRequests"
        $Table.TableStyle = "TableStyleMedium6"

        if (Test-Path $InputPath) { Remove-Item $InputPath -Force }
        $Wb.SaveAs($InputPath, 51)
        $Wb.Close($false)
        $Excel.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($Excel) | Out-Null
        Write-Ok "PatientInput.xlsx created at Data\"
    } catch {
        Write-Warn "Excel COM failed: $_"
        Write-Warn "PatientInput.xlsx not created. Please create it manually."
    }
}

# ---------------------------------------------------------------------------
# STEP 8 – Create Notifications output folder
# ---------------------------------------------------------------------------
Write-Step "Creating Notifications output folder"
$NotifDir = Join-Path $ProjectRoot "Data\Notifications"
if (-not (Test-Path $NotifDir)) {
    New-Item -ItemType Directory -Path $NotifDir -Force | Out-Null
    Write-Ok "Created: Data\Notifications"
}

# ---------------------------------------------------------------------------
# STEP 9 – Validate setup
# ---------------------------------------------------------------------------
Write-Step "Validating setup"

$Checks = @(
    @{ Path = "Data\HospitalDB.db";        Label = "SQLite Database" },
    @{ Path = "Data\Config.xlsx";          Label = "Config.xlsx" },
    @{ Path = "Data\PatientInput.xlsx";    Label = "PatientInput.xlsx" },
    @{ Path = "Scripts\InitDB.sql";        Label = "InitDB.sql" },
    @{ Path = "Scripts\TestReset.sql";     Label = "TestReset.sql" },
    @{ Path = "Patients\P1024\ID_Proof.pdf";       Label = "P1024 ID_Proof" },
    @{ Path = "Patients\P1025\Consent_Form.pdf";   Label = "P1025 Consent_Form" },
    @{ Path = "Framework";                 Label = "Framework folder" },
    @{ Path = "Workflows";                 Label = "Workflows folder" }
)

$AllOk = $true
foreach ($chk in $Checks) {
    $fullPath = Join-Path $ProjectRoot $chk.Path
    if (Test-Path $fullPath) {
        Write-Ok "$($chk.Label)"
    } else {
        Write-Warn "MISSING: $($chk.Label) → $($chk.Path)"
        $AllOk = $false
    }
}

Write-Host ""
if ($AllOk) {
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host " SETUP COMPLETE – All Phase 2 assets created successfully." -ForegroundColor Green
    Write-Host " Next step: Phase 3 – UiPath project structure and configuration" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
} else {
    Write-Host "================================================================" -ForegroundColor Yellow
    Write-Host " SETUP PARTIALLY COMPLETE – Some items need manual attention." -ForegroundColor Yellow
    Write-Host " Review the warnings above and address missing items." -ForegroundColor Yellow
    Write-Host "================================================================" -ForegroundColor Yellow
}
