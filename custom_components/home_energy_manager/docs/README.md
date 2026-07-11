# Home Energy Manager v0.2.1

Nieuwe read-only energiesensoren:

- **Huidige energie** = som van capaciteit per accu × individueel SoC.
- **Reserve-energie** = 20% van de totale nominale capaciteit.
- **Beschikbare energie** = huidige energie minus reserve, minimaal 0 Wh.

## Bijwerken

1. Vervang `/config/custom_components/home_energy_manager` door de map uit dit ZIP-bestand.
2. Herstart Home Assistant volledig.
3. De bestaande integratieconfiguratie blijft behouden.

Bij 3 × 2400 Wh en 95% SoC:

- Huidige energie: 6840 Wh
- Reserve-energie: 1440 Wh
- Beschikbare energie: 5400 Wh

Deze versie stuurt nog geen MQTT-commando's. Het reservepercentage maken we
in de volgende kleine stap instelbaar.
