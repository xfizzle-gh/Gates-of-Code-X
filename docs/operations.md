# Operations

## Install

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_gates_of_codex.ps1
```

## Validate installation

```powershell
gates-of-codex doctor
gates-of-codex scan --codex "E:\Steam\steamapps\workshop\content\400750\<CODEX_ID>"
```

## Run tests

```powershell
py -3.11 -m pip install -e .
py -3.11 -m unittest discover -s tests -v
```

## Live acceptance

Create a fresh campaign, move a battalion into a hostile province, export a battle using a valid Code:X map identifier, play the generated Dynamic Conquest save in Gates of Hell, and import the updated save. Verify unit equipment, vehicle crews, stage ownership, mission completion, surviving squads, retreat behavior, and province ownership.
