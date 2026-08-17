# Lithuania's pole of remoteness

The point on Lithuanian land farthest from any drivable road, roads in all neighboring countries included. Water (sea, lagoon, lakes > 0.5 km²) excluded from candidate locations. OSM data snapshot: 2026-08-17T17:06Z.

## Scenario A: any drivable way (incl. track)

Road network: 543,644 ways, 196,903 km.

### Winner: 3.43 km from the nearest road

- **Where:** 3.7 km S of Kumečiai, inside Žuvinto biosferos rezervatas
- **WGS84:** 54.441473, 23.537020 · **LKS-94:** 469968, 6033948
- **Nearest road:** `highway=track`, in Lithuania ([way 1385319417](https://www.openstreetmap.org/way/1385319417))
- [OpenStreetMap](https://www.openstreetmap.org/?mlat=54.441473&mlon=23.537020#map=13/54.441473/23.537020) · [Google Maps (satellite)](https://www.google.com/maps?q=54.441473,23.537020&t=k)

### Runners-up (mutually > 10 km apart)

| # | km to road | Where | Coordinates | Nearest road |
|---|---|---|---|---|
| 2 | 3.41 | 4.4 km NW of Katra (Čepkelių valstybinis gamtinis rezervatas) | [54.01064, 24.52937](https://www.openstreetmap.org/?mlat=54.010641&mlon=24.529371#map=13/54.010641/24.529371) | track, Lithuania |
| 3 | 2.56 | 4.1 km E of Ašvėnai (Kamanų valstybinis gamtinis rezervatas) | [56.28258, 22.64181](https://www.openstreetmap.org/?mlat=56.282578&mlon=22.641810#map=13/56.282578/22.641810) | track, Lithuania |
| 4 | 2.15 | 6.4 km SW of Vorusnė | [55.24836, 21.26211](https://www.openstreetmap.org/?mlat=55.248363&mlon=21.262109#map=13/55.248363/21.262109) | track, Russia (Kaliningrad) |
| 5 | 2.13 | 2.8 km S of Juodeikiai | [56.21594, 23.22850](https://www.openstreetmap.org/?mlat=56.215939&mlon=23.228502#map=13/56.215939/23.228502) | tertiary, Lithuania |
| 6 | 2.08 | 2.1 km E of Šalnakandžiai | [55.78131, 25.01406](https://www.openstreetmap.org/?mlat=55.781309&mlon=25.014061#map=13/55.781309/25.014061) | track, Lithuania |

## Scenario B: public roads (no track)

Road network: 393,100 ways, 120,153 km.

### Winner: 6.67 km from the nearest road

- **Where:** 6.6 km E of Grybaulia, inside Čepkelių valstybinis gamtinis rezervatas
- **WGS84:** 53.995818, 24.462993 · **LKS-94:** 530358, 5984353
- **Nearest road:** `highway=unclassified`, surface=unpaved, "Baublių g.", in Lithuania ([way 70542812](https://www.openstreetmap.org/way/70542812))
- [OpenStreetMap](https://www.openstreetmap.org/?mlat=53.995818&mlon=24.462993#map=13/53.995818/24.462993) · [Google Maps (satellite)](https://www.google.com/maps?q=53.995818,24.462993&t=k)

### Runners-up (mutually > 10 km apart)

| # | km to road | Where | Coordinates | Nearest road |
|---|---|---|---|---|
| 2 | 4.94 | 5.8 km SE of Musteika | [53.91016, 24.40710](https://www.openstreetmap.org/?mlat=53.910157&mlon=24.407101#map=13/53.910157/24.407101) | residential, Lithuania |
| 3 | 4.83 | 2.8 km NW of Leipgiriai | [55.12806, 22.43524](https://www.openstreetmap.org/?mlat=55.128063&mlon=22.435240#map=13/55.128063/22.435240) | service, Lithuania |
| 4 | 4.69 | 4.3 km NW of Visinčia | [54.35550, 25.03302](https://www.openstreetmap.org/?mlat=54.355498&mlon=25.033019#map=13/54.355498/25.033019) | service, Lithuania |
| 5 | 3.90 | 2.9 km NW of Globiai | [55.20544, 22.57196](https://www.openstreetmap.org/?mlat=55.205444&mlon=22.571962#map=13/55.205444/22.571962) | unclassified, Lithuania |
| 6 | 3.89 | 4.3 km NE of Zervynos | [54.13832, 24.54332](https://www.openstreetmap.org/?mlat=54.138317&mlon=24.543317#map=13/54.138317/24.543317) | secondary, Lithuania |

## Verification

- Cross-border road data survived clipping: 252 Belarusian ways near Čepkeliai, 8426 Polish ways near Kalvarija.
- Border-strip roads within 1.2 km of the LT–BY border at Čepkeliai (patrol-road check): {"Belarus/residential": 11, "Belarus/secondary": 7, "Belarus/service": 30, "Belarus/tertiary": 8, "Belarus/track": 203, "Belarus/unclassified": 11, "Lithuania/residential": 8, "Lithuania/secondary": 7, "Lithuania/service": 25, "Lithuania/tertiary": 7, "Lithuania/track": 210, "Lithuania/unclassified": 9}.
- Winners verified on land and inside Lithuania; exact vector re-check and 1 m densified nearest-way check both agree with reported distances.
- Sanity: scenario A distance ≤ scenario B distance: True.
