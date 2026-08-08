# Issue 161 native wrapper engine acceptance

This audit-only branch descends from exact accepted implementation commit:

`14d784de63d58ddbf993d71f95d9f31b8a370cb2`

It adds no gameplay or wrapper implementation changes.

Validated audit-runner head:

`424709e3c24cd274df7d37ca33259e27b7ee41b4`

Dedicated preflight run:

`31276350695`

## Prepare and launch

From the independent audit worktree:

```powershell
cd "E:\Steam\steamapps\workshop\content\400750\Gates-of-Code-X-faction-audit"
git fetch origin
git switch -C audit/161-wrapper-engine-acceptance origin/audit/161-wrapper-engine-acceptance
& ".\audit\issue161\prepare-wrapper-test.ps1" `
  -ProfileDirectory "C:\Users\paulf\AppData\Local\digitalmindsoft\gates of hell\profiles" `
  -InstallDirectory "C:\Users\paulf\AppData\Local\digitalmindsoft\gates of hell\profiles\46383268\campaign"
```

The script validates the exact audit ancestry and file scope, installs the Python 3.11.9 environment, validates the five-layer stack, validates all 14 exact native wrapper definitions, migrates the bundled legacy campaign to the same deterministic strategic-formation layer used by `CampaignEngine`, installs two disposable Conquest saves, prints their exact visible names, and launches GoH.

Load the Ukraine-player save first, then the Russia-player save. Take screenshots covering ILDU, Sparta, Vostok, and Serbia.

## Collect evidence

After exiting GoH:

```powershell
& ".\audit\issue161\collect-wrapper-evidence.ps1"
```

Complete the generated wrapper result matrix and upload the Desktop ZIP to issue #161.
