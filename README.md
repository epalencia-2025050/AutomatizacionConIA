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
copy .env.example .env 2>nul         # o edita directamente .env
```

Edita `.env`:

```ini
SAT_NIT=1234567890           # NIT (o CUI), sin guiones
SAT_PASSWORD=TuClaveSegura    # contraseña de Agencia Virtual
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
| 2 | Procesamiento XML + BD SQLite | ✅ **Implementada - 16 tests OK** |
| 3 | Transferencia a página destino | pendiente (URL aún desconocida) |
| 4 | Integración + GUI Tkinter + reportes | pendiente |

## Seguridad

- Credenciales SOLO en `.env` (gitignored).
- No se evaden CAPTCHA ni el segundo factor: requieren intervención humana.
- La sesión guardada sirve de contexto de trabajo, hay que renovarla
  manualmente si la Agencia Virtual la invalida.
