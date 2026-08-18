# Changelog



## Zendure Firmware update results in MQTT down when Hems is active (18-08-2026)

## v0.4.0

- Directe MQTT-besturing van fysieke Zendure SolarFlow-units
- AC-modus per SolarFlow: Input mode / Output mode
- Off-gridmodus per SolarFlow
- Input- en outputlimiet per SolarFlow
- Minimum SoC en doel-SoC per SolarFlow
- Pack-status toegevoegd
- BMS-monitoring toegevoegd:
  - hoogste batterijtemperatuur
  - hoogste celspanning
  - laagste celspanning
  - celspanningsverschil
- Individuele PV-ingangen 1 t/m 4 per SolarFlow
- Totaal PV-ingangsvermogen per SolarFlow
- Ondersteuning voor Zendure batterijpack-MQTT-topics met JO2-device-ID prefix
- Verbeterde MQTT-diagnostiek en terugmelding

## v0.3.0.1

- Netto batterijvermogen sensor toegevoegd

## v0.3.0

- Eerste stabiele/professionele release van Home Energy Manager
- Ondersteuning voor meerdere Zendure SolarFlow-batterijen
- Virtuele batterij voor het combineren van meerdere accu's
- Totale nominale capaciteit
- Huidige energie
- Beschikbare energie
- Reserve-energie
- Gemiddeld laadniveau
- Hoogste en laagste SoC
- Balanscontrole tussen accu's
- Totaal laad- en ontlaadvermogen
- PV-ingangsvermogen
- AC-ingangsvermogen
- Uitgaand vermogen naar huis
- Configuratie via Home Assistant config flow
- Nederlandse en Engelse vertalingen

## 0.2.1

- Huidige energie toegevoegd.
- Reserve-energie toegevoegd.
- Beschikbare energie toegevoegd.
- Reserve staat voorlopig vast op 20%.
- Volledig read-only.

## 0.1.0

- Eerste uitleesversie.
