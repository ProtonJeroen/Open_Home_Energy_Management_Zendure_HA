# Home Energy Manager

Een Home Assistant-integratie voor het lokaal uitlezen en aansturen van Zendure
SolarFlow-systemen via MQTT. Combineert meerdere accu's tot een virtuele batterij
en gebruikt een ingestelde netvermogenssensor, bijvoorbeeld HomeWizard P1, voor
de bestaande vermogensregeling.

## Installeren via HACS

Vereist HACS en een werkende MQTT-integratie in Home Assistant.
De SolarFlows moeten hun lokale MQTT-data naar dezelfde broker sturen. HACS
installeert de integratiebestanden; het configureert de Zendure-apparaten niet.

1. Open HACS en kies via het menu rechtsboven **Aangepaste repositories**.
2. Voeg `https://github.com/ProtonJeroen/Open_Home_Energy_Management_Zendure_HA`
   toe met type **Integratie**.
3. Zoek **Home Energy Manager** in HACS en download de integratie.
4. Herstart Home Assistant.
5. Ga naar **Instellingen → Apparaten & diensten → Integratie toevoegen** en
   kies **Home Energy Manager**.
6. Selecteer de gevraagde sensoren en stel capaciteit en netvermogenssensor in.
   Automatische batterijbesturing staat standaard uit; controleer de metingen
   en limieten voordat je die in de integratieopties inschakelt.

De repository moet openbaar zijn voordat HACS deze kan ophalen. Opname in de
algemene HACS-catalogus is niet nodig voor deze aangepaste repository.

## Een bestaande handmatige installatie overnemen

Maak vooraf een Home Assistant-back-up, inclusief
`custom_components/home_energy_manager`, vooral als je losse 5y/5z-bestanden
hebt geïnstalleerd. HACS vervangt die bestanden door de repositoryversie.
De losse 5y/5z-downloads uit eerdere chats zijn niet in deze versie opgenomen.

Voeg de repository toe in HACS, download en herstart Home Assistant. Verwijder
de bestaande Home Energy Manager-integratie niet: de domeinnaam en unieke
entity-ID's blijven gelijk, zodat de bestaande configuratie behouden kan blijven.
Controleer daarna de sensoren en de automatische koppeling naar de limieten.

## Updates

HACS biedt toekomstige updates aan. Download de update en herstart Home
Assistant. Zolang er geen GitHub-releases zijn, gebruikt HACS de standaardbranch
`main`; de weergegeven updateversie kan dan een korte commitcode zijn.

## Huidige versie: 0.5.1

- De bestaande 0.5-regeling en de 5aa-fix voor Doelvermogen-listeners.
- Koppeling naar Zendure-limieten via stabiele unieke sensor-ID's, ook na hernoemen.
- HACS-configuratie, installatie-instructies en correcte repositorylinks.
- De automatische besturing is momenteel gericht op SolarFlows met de korte
  IDs `040363`, `040453` en `040458`; dit is nog geen algemene regelaar voor
  willekeurige apparaat-ID's.

Compilecontrole en geïsoleerde controllertests zijn uitgevoerd. De werking op
een echte Home Assistant-installatie en firmware V2.0.4 moet nog worden getest.
Zie [de praktijkcontrole voor 5aa](custom_components/home_energy_manager/docs/5aa-review.md)
en het [changelog](custom_components/home_energy_manager/docs/CHANGELOG.md).

## Ondersteuning

Meld problemen via [GitHub Issues](https://github.com/ProtonJeroen/Open_Home_Energy_Management_Zendure_HA/issues).
Vermeld Home Assistant-versie, firmwareversie en relevante logregels; verwijder
wachtwoorden en andere toegangsgegevens voordat je logs deelt.

