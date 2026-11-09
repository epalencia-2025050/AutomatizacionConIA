# Automatización de facturas SAT Guatemala — Fase 1

Descarga automática de **DTE (facturas electrónicas) recibidos** desde la
**Agencia Virtual de SAT Guatemala**, organizándolos en carpetas según su
estado. Flujo:

```
Agencia Virtual (login + 2FA) → Consultar DTE (Recibidos) → Descargar XML/PDF
        → data/processed (válidos) / data/errors (vacíos)
```

[![Python](https://img.shields.io/badge/python-3.12+-blue)]()
[![Fase](https://img.shields.io/badge/fase-1_activa-green)]()

## Instalación

```bash
python -m venv venv
venv\Scripts\activate                # Windows
pip install -r requirements.txt
playwright install chromium          # descargar navegador Chromium
copy .env.example .env                # o edita directamente .env
```

Edita `.env` y completa tus credenciales. También se admite `src\.env`;
si ambos archivos existen, los valores de `.env` en la raíz tienen prioridad.

```ini
SAT_NIT=tu_NIT                # NIT (o CUI), sin guiones
SAT_PASSWORD=tu_clave         # contraseña de Agencia Virtual
```

## Uso

```bash
python main.py                                         # últimos 7 días
python main.py --date-from 01/10/2026 --date-to 15/10/2026
python main.py --dry-run                               # listado sin descargar
```

Durante la ejecución (transacción interactiva):

1. Se abre Chromium **visible** (`headless: false` en `config/settings.yaml`).
2. Si no hay sesión previa, escribes NIT/contraseña automáticamente y
   **aguarda tu código de 6 dígitos de Microsoft Authenticator** (180 s).
3. La sesión queda guardada en `storage/sat_av_state.json` (gitignored)
   para no repetir el login ni el 2FA en corridas siguientes.
4. Consulta los DTE recibidos del rango de fechas y descarga XML + PDF.
5. En modo visible, el navegador SAT permanece abierto al terminar esa fase;
   pulsa Enter en la consola para cerrarlo y continuar. En modo headless no espera.
   Si la navegación automática al módulo no encuentra el menú, puedes abrir
   manualmente "Consultar DTE" en esa ventana y pulsar Enter para que continúe.

## Estructura

```
src/sat/        login, consulta y descarga (Fase 1)
src/processing/ interpretación XML (Fase 2 - pendiente)
src/destination/ integración sitio destino (Fase 3 - pendiente)
src/database/   SQLite (Fase 2 - pendiente)
src/reports/    reportes (Fase 4 - pendiente)
tools/          herramientas de respaldo (ex: selector discovery)
```

## Después del primer login

La pantalla interna "Consultar DTE" solo es visible con sesión activa.
Si el flujo de filtrado por fechas no llega, ejecuta:

```bash
python tools/discover_dte_selectors.py
```

conéctate al módulo y pega a `config/settings.yaml` →
`sat.consulta_dte_url` la URL exacta que aparece en la barra de tu navegador.
Ese mismo snapshot te permite ajustar `config/selectors.yaml` si el portal
cambia o si la página tiene selectores propios no genéricos.

## Estado del proyecto

| Fase | Descripción | Estado |
|---|---|---|
| 1 | Consulta y descarga DTE SAT GT | 🔄 MVP listo para validar en vivo |
| 2 | Procesamiento XML + BD SQLite | ✅ Implementada |
| 3 | Transferencia a Odoo | 🏗️ **Módulo Odoo listo - falta URL de instancia + mapeo de form** |
| 4 | Integración + GUI Tkinter + reportes | ✅ **Implementada - 34 tests OK** |
| 5 | Mejora: Odoo por XML-RPC (sin navegador) | ✅ **Implementada - 40 tests OK** |
| 6 | Mejora: reintentos con backoff + ejecución diaria + backup BD | ✅ **Implementada - 48 tests OK** |
| 7 | Mejora: reporte por correo + alerta 2FA + visor de BD en la GUI | ✅ **Implementada - 54 tests OK** |

## Fase 7 — Notificaciones y visor

### Correo con el reporte (activable cuando gustes)
1. En tu Google: **Verificación en 2 pasos** → **Contraseñas de aplicación** → genera una (16 letras; no es tu contraseña personal)
2. `.env` → `MAIL_USER=`, `MAIL_PASS=`, `MAIL_TO=`
3. `settings.yaml` → `notifications.email.activar: true`
Desde entonces cada corrida envía a tu correo el CSV con el detalle. (SMTP genérico: sirve Gmail u otro proveedor; falla silenciosamente si el correo no funciona).

### Alerta de 2FA
Cuando el SAT pide el código doble-factactor: suena la campana y avisa en la GUI, y si el
correo está activado te manda "⚠ SAT requiere tu 2FA ahora".

### Visor de BD en la GUI
Sección "Facturas en la base de datos": filtro por texto y estado, lista con
emisión/NIT/emisor/total/estado/UUID y contador de subidas — sin abrir DB Browser.

## Fase 6 — Robustez automática

### Reintentos con espera progresiva
Si una fase falla (red, portal), espera **1 → 2 → 5 min** y reintenta (configurable en
`settings.yaml → reintentos`). Al agotarse, la corrida termina con el error registrado en el log.

### Wizard de programación diaria (una vez, como Administrador)
```bat
tools\programar_tarea_diaria.bat     REM corre todos los días 08:00 desatendido
tools\desprogramar_tarea.bat         REM cancela la programación
```
La tarea ejecuta `python main.py --headless`; existe el flag `--headless` para cualquier ejecución sin ventana (en la GUI también hay casilla).

### Backup diario de la BD
Cada corrida garantiza `data/backups/automatizacion_YYYYMMDD.db` (una por día) y conserva
los últimos 30 (`settings.yaml → backups`). Permite recuperar el histórico si algo sale mal —
la BD real nunca se toca al hacer copias.

## Fase 4 — GUI, reportes y recuperación

### Interfaz gráfica
```bash
python main.py --gui
```
- **▶ Ejecutar todo**: consulta SAT → descarga → procesa XML → BD → sube a destino (si está habilitado) → genera reporte
- **⚙ Solo procesar XML**: Fase 2 sobre lo ya descargado (sin conectar al SAT)
- **⇪ Solo subir a destino (Odoo)**: transfiere VALIDADA/PENDIENTE_SUBIDA (requiere Fase 3 activa)
- **↻ Reprocesar errores**: devuelve `data/errors/*` a `data/downloads` y re-lanza el pipeline (errores temporales de red/portal)
- **📄 Generar reporte**: CSV con estado actual de la BD
- Filtros opcionales: rango de fechas `dd/mm/yyyy` y modo headless del navegador
- Log en vivo en pantalla + `logs/automatizacion.log`

### Reportes
Cada corrida genera `data/reports/reporte_YYYYMMDD_HHMM.csv` (UTF-8 con BOM,
abre directo en Excel) con secciones:
- `EJECUCION`: rango de fechas y conteos del flujo
- `ESTADO_BD`: resumen de la máquina de estados (DESCARGADA/SUBIDA/...)
- `DETALLE`: una fila por factura con uuid, emisor, total, estado, rutas XML/PDF y fecha de carga

### Recuperación
Las facturas con ERROR conservan `intentos` y el motivo; la GUI permite
reintentarlas con un clic. Los archivos con XML inválido van a
`data/errors/` y se pueden reprocesar cuando el problema (red, portal) se resuelva.

## Fase 3 — Destino: Odoo

El módulo de Odoo ya está implementado (`src/destination/odoo.py`) con el **login estándar de Odoo verificado** (`/web/login`, campos `login`/`password`). Para activar la transferencia:

1. `config/settings.yaml` →
   ```yaml
   destination:
     habilitado: true
     url: https://TU-INSTANCIA.odoo.com     # pega tu URL real
     modulo: odoo
   ```
2. `.env` → `DEST_USER` (tu email de Odoo) y `DEST_PASSWORD`
3. Completa el mapeo del formulario con la herramienta:
   ```bash
   python tools/discover_odoo.py https://TU-INSTANCIA.odoo.com
   ```
   Inicia sesión, navega a *Contabilidad → Facturas de proveedor → Nueva*,
   pulsa `[i]` y copia los `input[name=...]` reportados a
   `config/selectors.yaml → destination.odoo` (campos: proveedor,
   referencia, total, adjunto XML/PDF, botón guardar).
4. Prueba: `python main.py --solo-subir`

> **Modalidad recomendada (Fase 5): XML-RPC.** Odoo trae API integrada en
> todas las versiones: en `settings.yaml` pon
> `destination.modulo: "odoo_xmlrpc"` y en `destination.xmlrpc.db:` el
> nombre de tu base de datos (sin tocar código). Ventajas: no se rompe
> con cambios de interfaz, confirmación 100% verificable y
> anti-duplicados por UUID antes de crear. El mismo DEST_USER /
> DEST_PASSWORD sirve — el flujo por navegador queda como alternativa.

## Seguridad

- Credenciales SOLO en `.env` (gitignored).
- No se evaden CAPTCHA ni el segundo factor: requieren intervención humana.
- La sesión guardada sirve de contexto de trabajo, hay que renovarla
  manualmente si la Agencia Virtual la invalida.
