# 5aa: Doelvermogen naar Zendure-limieten

Deze minimale fix is gebaseerd op branch `v0.5.0`, commit
`adc41284b00597eb626a2b02e408458a1f10f0fd`. Op `main` staat nog 0.4.0
zonder de automatische controller. De losse 5y/5z-bestanden uit de eerdere
chat zijn niet aanwezig in de repository; deze wijziging importeert die niet.

## Bevinding en wijziging

`SolarFlowTargetPowerSensor` heeft unique ID
`<config_entry_id>_target_power_<short_id>`. Home Assistant bepaalt de
entity-ID onafhankelijk daarvan. De controller luisterde naar vaste
`sensor.doelvermogen_...`-namen en haalde het apparaatnummer uit de laatste
underscore-sectie. Een prefix, suffix zoals `_2` of een hernoeming verbreekt
daardoor de koppeling.

De controller zoekt nu de echte entity-ID op in de entity registry via
platform, domein en unique ID. Een expliciete mapping koppelt die ID aan de
bestaande drie SolarFlows. Registrywijzigingen vernieuwen de listener als de
mapping verandert. Beide listeners worden bij unload opgeruimd.

De regelberekeningen, limieten, tekenrichting, MQTT-publicatievolgorde en
onderdrukking van dubbele opdrachten zijn ongewijzigd. `sensor.py` en Smart
EV Charging zijn niet aangepast.

## Validatie

- `python -m compileall -q custom_components tests`
- `python -m unittest discover -s tests -v`: vier regressietests.
- Tests voeren de daadwerkelijke controllerklasse uit met gesimuleerde HA-
  registry, events en MQTT-publicatie. Ze controleren afwijkende namen bij
  alle drie de apparaten, late registratie, hernoeming, unload, uitschakelen,
  ongeldige waarden, een andere config entry, ontbrekend MQTT-apparaat,
  laden/ontladen, begrenzing en dubbele opdrachten.

Dit is geen volledige Home Assistant-integratietest of hardwaretest. De
entity registry van de draaiende installatie is niet ingezien.

## Praktijkcontrole na review

1. Controleer dat automatische batterijbesturing aan staat en de SolarFlows
   live MQTT-data leveren; beide bestaande voorwaarden blijven gelden.
2. Bekijk de echte Doelvermogen-entity-ID's in Home Assistant. Met debuglogging
   voor deze integratie toont `SolarFlow doelvermogen-koppelingen` de mapping.
3. Bij een gewijzigde Doelvermogen-waarde van -148 W moet voor hetzelfde
   apparaat `inputLimit/set = 0` en `outputLimit/set = 148` verschijnen.
   Bij +148 W hoort dat respectievelijk 148 en 0 te zijn.
4. Hernoem een Doelvermogen-entity en controleer bij een volgende wijziging
   dat dezelfde SolarFlow wordt aangestuurd. Controleer vervolgens ook het
   fysieke vermogen en de P1-terugmelding.

De fix verandert geen doelwaarden of startgedrag: opdrachten volgen zoals
voorheen op state-change-events. Andere naamafhankelijkheden in de bestaande
vermogensberekening vallen buiten deze wijziging.
