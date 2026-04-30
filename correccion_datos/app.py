from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse
import os

import pandas as pd
import requests
import mysql.connector
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import config


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _create_root() -> tk.Tk:
    try:
        import ttkbootstrap as ttkb  # type: ignore

        root = ttkb.Window(themename="flatly")
        return root
    except Exception:
        root = tk.Tk()
        try:
            ttk.Style(root).theme_use("clam")
        except Exception:
            pass
        return root


def _normalize_base_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        return config.API_BASE_URL
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    if not value.endswith("/"):
        value += "/"
    return value


def _origin_from_base_url(base_url: str) -> str:
    p = urlparse(base_url)
    return f"{p.scheme}://{p.netloc}"


def _validate_identifier(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label} es obligatorio.")
    if not _IDENT_RE.fullmatch(value):
        raise ValueError(f"{label} inválido: {value!r}")
    return value


def _connect_db(host: str, user: str, password: str, database: str):
    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        connection_timeout=10,
    )


@dataclass
class _State:
    registros_encontrados: list[str]
    dnis_sin_datos: list[dict[str, str]]
    datos_extraidos: list[dict[str, Any]]


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Corrección de datos")
        self.root.geometry("1100x800")

        self.state = _State(registros_encontrados=[], dnis_sin_datos=[], datos_extraidos=[])
        self.stop_event = threading.Event()
        self._worker: threading.Thread | None = None

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._log_registro: list[str] = []

        self._build_ui()
        self.root.after(75, self._drain_log_queue)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=10)
        container.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill="both", expand=True)

        self.tab_db = ttk.Frame(self.notebook, padding=10)
        self.tab_web = ttk.Frame(self.notebook, padding=10)
        self.tab_mapeo = ttk.Frame(self.notebook, padding=10)
        self.tab_ejecucion = ttk.Frame(self.notebook, padding=10)
        self.tab_log = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.tab_db, text="Base de datos")
        self.notebook.add(self.tab_web, text="Web")
        self.notebook.add(self.tab_mapeo, text="Mapeo")
        self.notebook.add(self.tab_ejecucion, text="Ejecución")
        self.notebook.add(self.tab_log, text="Log")

        self._build_tab_db()
        self._build_tab_web()
        self._build_tab_mapeo()
        self._build_tab_ejecucion()
        self._build_tab_log()

    def _row(self, parent: ttk.Frame, row: int, label: str, width: int = 34, show: str | None = None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, width=width, show=show)
        entry.grid(row=row, column=1, sticky="we", padx=(10, 0), pady=4)
        return entry

    def _build_tab_db(self) -> None:
        self.tab_db.columnconfigure(1, weight=1)

        self.host_entry = self._row(self.tab_db, 0, "Host")
        self.user_entry = self._row(self.tab_db, 1, "Usuario")
        self.password_entry = self._row(self.tab_db, 2, "Contraseña", show="•")
        self.db_entry = self._row(self.tab_db, 3, "Base de datos")
        self.tabla_entry = self._row(self.tab_db, 4, "Tabla")
        self.campo_dni_entry = self._row(self.tab_db, 5, "Campo DNI")
        self.campo_filtro_entry = self._row(self.tab_db, 6, "Campo filtro (opcional)")
        self.valor_filtro_entry = self._row(self.tab_db, 7, "Valor filtro (opcional)")

        self.host_entry.insert(0, config.DB_HOST)
        self.user_entry.insert(0, config.DB_USER)
        if config.DB_PASSWORD:
            self.password_entry.insert(0, config.DB_PASSWORD)
        self.db_entry.insert(0, config.DB_NAME)
        self.tabla_entry.insert(0, config.DB_TABLE)
        self.campo_dni_entry.insert(0, config.DB_DNI_FIELD)
        self.campo_filtro_entry.insert(0, config.DB_FILTER_FIELD)
        self.valor_filtro_entry.insert(0, config.DB_FILTER_VALUE)

        self.show_password_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.tab_db,
            text="Mostrar contraseña",
            variable=self.show_password_var,
            command=self._toggle_password,
        ).grid(row=8, column=1, sticky="w", pady=(8, 0))

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self.show_password_var.get() else "•")

    def _build_tab_web(self) -> None:
        self.tab_web.columnconfigure(1, weight=1)

        self.base_url_entry = self._row(self.tab_web, 0, "URL SEAAP (extracción) (ej: http://seaap.minsa.gob.pe/)")
        self.cf_bm_entry = self._row(self.tab_web, 1, "Cookie __cf_bm")
        self.session_id_entry = self._row(self.tab_web, 2, "Cookie session_id")
        self.uid_entry = self._row(self.tab_web, 3, "UID")

        self.base_url_entry.insert(0, config.API_BASE_URL)

    def _build_tab_mapeo(self) -> None:
        self.tab_mapeo.columnconfigure(1, weight=1)

        self.campo_apellidos_entry = self._row(self.tab_mapeo, 0, "Campo BD: apellidos")
        self.campo_nombres_entry = self._row(self.tab_mapeo, 1, "Campo BD: nombres")
        self.campo_fecha_entry = self._row(self.tab_mapeo, 2, "Campo BD: fecha_nacimiento")
        self.campo_name_entry = self._row(self.tab_mapeo, 3, "Campo BD: name")
        self.campo_direccion_entry = self._row(self.tab_mapeo, 4, "Campo BD: direccion")

        self.campo_apellidos_entry.insert(0, config.MAP_APELLIDOS)
        self.campo_nombres_entry.insert(0, config.MAP_NOMBRES)
        self.campo_fecha_entry.insert(0, config.MAP_FECHA_NAC)
        self.campo_name_entry.insert(0, config.MAP_NAME)
        self.campo_direccion_entry.insert(0, config.MAP_DIRECCION)

    def _build_tab_ejecucion(self) -> None:
        self.tab_ejecucion.columnconfigure(0, weight=1)

        actions = ttk.Frame(self.tab_ejecucion)
        actions.grid(row=0, column=0, sticky="we")

        self.btn_filtrar = ttk.Button(actions, text="Conectar y filtrar", command=self.conectar_y_filtrar)
        self.btn_filtrar.grid(row=0, column=0, padx=(0, 8))

        self.btn_automatizar = ttk.Button(actions, text="Automatizar", command=self.automatizar_actualizacion, state=tk.DISABLED)
        self.btn_automatizar.grid(row=0, column=1, padx=8)

        self.btn_detener = ttk.Button(actions, text="Detener", command=self.detener_proceso, state=tk.DISABLED)
        self.btn_detener.grid(row=0, column=2, padx=8)

        self.btn_exportar_log = ttk.Button(actions, text="Exportar log", command=self.exportar_log)
        self.btn_exportar_log.grid(row=0, column=3, padx=8)

        self.btn_exportar_excel = ttk.Button(actions, text="Exportar Excel", command=self.exportar_resultados, state=tk.DISABLED)
        self.btn_exportar_excel.grid(row=0, column=4, padx=(8, 0))

        self.stats_label = ttk.Label(self.tab_ejecucion, text="Registros encontrados: 0")
        self.stats_label.grid(row=1, column=0, sticky="w", pady=(12, 0))

        self.progress_var = tk.IntVar(value=0)
        self.progress_bar = ttk.Progressbar(self.tab_ejecucion, maximum=100, variable=self.progress_var)
        self.progress_bar.grid(row=2, column=0, sticky="we", pady=(8, 0))

        self.progress_text = ttk.Label(self.tab_ejecucion, text="0%")
        self.progress_text.grid(row=3, column=0, sticky="w", pady=(6, 0))

        self.time_text = ttk.Label(self.tab_ejecucion, text="")
        self.time_text.grid(row=4, column=0, sticky="w", pady=(4, 0))

    def _build_tab_log(self) -> None:
        self.log_text = ScrolledText(self.tab_log, height=28)
        self.log_text.pack(fill="both", expand=True)

    def log(self, mensaje: str) -> None:
        self._log_queue.put(mensaje)

    def _drain_log_queue(self) -> None:
        updated = False
        while True:
            try:
                msg = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._log_registro.append(msg)
            self.log_text.insert(tk.END, msg + "\n")
            updated = True
        if updated:
            self.log_text.see(tk.END)
        self.root.after(75, self._drain_log_queue)

    def _set_running(self, running: bool) -> None:
        if running:
            self.btn_filtrar.configure(state=tk.DISABLED)
            self.btn_automatizar.configure(state=tk.DISABLED)
            self.btn_detener.configure(state=tk.NORMAL)
            self.btn_exportar_excel.configure(state=tk.DISABLED)
        else:
            self.btn_filtrar.configure(state=tk.NORMAL)
            self.btn_detener.configure(state=tk.DISABLED)
            self.btn_automatizar.configure(state=tk.NORMAL if self.state.registros_encontrados else tk.DISABLED)
            has_data = bool(self.state.datos_extraidos or self.state.dnis_sin_datos)
            self.btn_exportar_excel.configure(state=tk.NORMAL if has_data else tk.DISABLED)

    def _read_db_inputs(self) -> dict[str, str]:
        host = self.host_entry.get().strip()
        user = self.user_entry.get().strip()
        password = self.password_entry.get()
        database = self.db_entry.get().strip()
        tabla = self.tabla_entry.get().strip()
        campo_dni = self.campo_dni_entry.get().strip()
        campo_filtro = self.campo_filtro_entry.get().strip()
        valor_filtro = self.valor_filtro_entry.get().strip()

        _validate_identifier(tabla, "Tabla")
        _validate_identifier(campo_dni, "Campo DNI")
        if campo_filtro:
            _validate_identifier(campo_filtro, "Campo filtro")

        if not (host and user and database):
            raise ValueError("Host, usuario y base de datos son obligatorios.")

        return {
            "host": host,
            "user": user,
            "password": password,
            "database": database,
            "tabla": tabla,
            "campo_dni": campo_dni,
            "campo_filtro": campo_filtro,
            "valor_filtro": valor_filtro,
        }

    def _read_web_inputs(self) -> dict[str, str]:
        base_url = _normalize_base_url(self.base_url_entry.get())
        cf_bm = self.cf_bm_entry.get().strip()
        session_id = self.session_id_entry.get().strip()
        uid = self.uid_entry.get().strip()
        if not (cf_bm and session_id and uid):
            raise ValueError("Cookie __cf_bm, session_id y UID son obligatorios.")
        int(uid)
        return {"base_url": base_url, "cf_bm": cf_bm, "session_id": session_id, "uid": uid}

    def _read_mapeo(self) -> dict[str, str]:
        return {
            "apellidos": self.campo_apellidos_entry.get().strip(),
            "nombres": self.campo_nombres_entry.get().strip(),
            "fecha_nacimiento": self.campo_fecha_entry.get().strip(),
            "name": self.campo_name_entry.get().strip(),
            "direccion": self.campo_direccion_entry.get().strip(),
        }

    def conectar_y_filtrar(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self.stop_event.clear()
        try:
            inputs = self._read_db_inputs()
        except Exception as e:
            messagebox.showerror("Validación", str(e))
            return

        self.state.registros_encontrados = []
        self.progress_var.set(0)
        self.progress_text.configure(text="0%")
        self.time_text.configure(text="")
        self.stats_label.configure(text="Registros encontrados: 0")
        self._set_running(True)
        self.log("Iniciando conexión y filtrado...")

        self._worker = threading.Thread(target=self._worker_filtrar, args=(inputs,), daemon=True)
        self._worker.start()

    def _worker_filtrar(self, inputs: dict[str, str]) -> None:
        try:
            conn = _connect_db(inputs["host"], inputs["user"], inputs["password"], inputs["database"])
        except Exception as e:
            self.root.after(0, lambda: self._on_filtrar_error(str(e)))
            return

        tabla = inputs["tabla"]
        campo_dni = inputs["campo_dni"]
        campo_filtro = inputs["campo_filtro"]
        valor_filtro = inputs["valor_filtro"]

        try:
            cursor = conn.cursor()
            if campo_filtro and valor_filtro:
                sql = f"SELECT {campo_dni} FROM {tabla} WHERE {campo_filtro} = %s"
                cursor.execute(sql, (valor_filtro,))
            else:
                sql = f"SELECT {campo_dni} FROM {tabla}"
                cursor.execute(sql)
            resultados = cursor.fetchall()
            registros = [str(r[0]) for r in resultados if r and r[0] is not None]
            self.root.after(0, lambda: self._on_filtrar_ok(registros))
        except Exception as e:
            self.root.after(0, lambda: self._on_filtrar_error(str(e)))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _on_filtrar_ok(self, registros: list[str]) -> None:
        self.state.registros_encontrados = registros
        total = len(registros)
        self.stats_label.configure(text=f"Registros encontrados: {total}")
        self.log(f"Registros encontrados: {total}")
        self._set_running(False)

    def _on_filtrar_error(self, error: str) -> None:
        self.log(f"Error en filtrado: {error}")
        messagebox.showerror("Error", error)
        self._set_running(False)

    def detener_proceso(self) -> None:
        self.stop_event.set()
        self.log("Proceso detenido por el usuario.")

    def automatizar_actualizacion(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self.stop_event.clear()

        try:
            db_inputs = self._read_db_inputs()
            web_inputs = self._read_web_inputs()
            mapeo = self._read_mapeo()
        except Exception as e:
            messagebox.showerror("Validación", str(e))
            return

        if not self.state.registros_encontrados:
            messagebox.showinfo("Sin registros", "Primero conecta y filtra.")
            return

        self.state.dnis_sin_datos = []
        self.state.datos_extraidos = []
        self.progress_var.set(0)
        self.progress_text.configure(text="0%")
        self.time_text.configure(text="")
        self._set_running(True)
        self.log("Iniciando automatización...")

        self._worker = threading.Thread(
            target=self._worker_automatizar, args=(db_inputs, web_inputs, mapeo), daemon=True
        )
        self._worker.start()

    def _worker_automatizar(self, db_inputs: dict[str, str], web_inputs: dict[str, str], mapeo: dict[str, str]) -> None:
        try:
            conn = _connect_db(db_inputs["host"], db_inputs["user"], db_inputs["password"], db_inputs["database"])
        except Exception as e:
            self.root.after(0, lambda: self._on_automatizar_error(str(e)))
            return

        base_url = web_inputs["base_url"]
        dataset_url = urljoin(base_url, "web/dataset/call_kw/actividades.actor/onchange")
        origin = _origin_from_base_url(base_url)
        referer = urljoin(base_url, "web?")

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "es-PE,es-US;q=0.9,es-419;q=0.8,es;q=0.7",
            "Content-Type": "application/json",
            "Origin": origin,
            "Referer": referer,
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
            "Connection": "keep-alive",
            "DNT": "1",
        }

        cookie_header = f"website_lang=es_PE; session_id={web_inputs['session_id']}; __cf_bm={web_inputs['cf_bm']}"
        uid = int(web_inputs["uid"])

        tabla = db_inputs["tabla"]
        campo_dni = db_inputs["campo_dni"]

        session = requests.Session()
        total = len(self.state.registros_encontrados)
        inicio = time.time()

        for idx, dni in enumerate(self.state.registros_encontrados):
            if self.stop_event.is_set():
                break

            self.log(f"Consultando DNI: {dni}")

            payload = {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "model": "actividades.actor",
                    "method": "onchange",
                    "args": [
                        [],
                        {
                            "id": False,
                            "state": False,
                            "tipo_id": False,
                            "dni": dni,
                            "apellidos": False,
                            "nombres": False,
                            "direccion": False,
                            "fecha_nacimiento": False,
                            "email": False,
                            "telefono": False,
                            "idioma_id": 1,
                            "grado_instruccion_seaap": False,
                            "grado_instruccion": False,
                            "active": True,
                            "inactivo_permanente": False,
                            "name": False,
                            "comiteial_id": False,
                            "comiteial_distrito_id": False,
                            "es_rural": False,
                            "centropoblado_id": False,
                            "comite_eess_ids": [],
                            "establecimiento_id": False,
                            "capvd_calidad": False,
                            "tipo_entidad": False,
                            "entidad_id": False,
                            "sectorial_sectorizacion_ids": [],
                            "sector_ial_ids": [],
                            "registro_ids": [],
                            "line_manzana_ids": [],
                            "capacitacion_id": [],
                            "message_follower_ids": False,
                            "message_ids": False,
                        },
                        "dni",
                        {
                            "state": "",
                            "tipo_id": "1",
                            "id": "",
                            "dni": "1",
                            "apellidos": "",
                            "nombres": "",
                            "direccion": "",
                            "fecha_nacimiento": "",
                            "email": "",
                            "telefono": "",
                            "idioma_id": "",
                            "grado_instruccion_seaap": "1",
                            "grado_instruccion": "1",
                            "active": "",
                            "inactivo_permanente": "",
                            "name": "",
                            "comiteial_id": "1",
                            "comiteial_distrito_id": "",
                            "es_rural": "",
                            "centropoblado_id": "1",
                            "comite_eess_ids": "",
                            "comite_eess_ids.red_id": "1",
                            "comite_eess_ids.codigo_eess": "",
                            "comite_eess_ids.microred_id": "1",
                            "comite_eess_ids.institucion": "",
                            "comite_eess_ids.diresa_id": "",
                            "establecimiento_id": "",
                            "capvd_calidad": "",
                            "tipo_entidad": "1",
                            "entidad_id": "",
                            "sectorial_sectorizacion_ids": "1",
                            "sector_ial_ids": "1",
                            "registro_ids": "1",
                            "registro_ids.paciente_id": "1",
                            "registro_ids.eess_id": "",
                            "registro_ids.fecha_visita_3": "1",
                            "registro_ids.fecha_visita_2": "1",
                            "registro_ids.fecha_visita_1": "1",
                            "registro_ids.ficha": "1",
                            "registro_ids.estado": "",
                            "registro_ids.observaciones": "",
                            "registro_ids.tiempo_visita_3": "",
                            "registro_ids.tiempo_visita_2": "",
                            "registro_ids.tiempo_visita_1": "",
                            "registro_ids.create_date": "",
                            "registro_ids.fecha_nac": "",
                            "registro_ids.tipo_actor_id": "",
                            "registro_ids.actor_id": "1",
                            "registro_ids.estado_visita_1": "",
                            "registro_ids.estado_visita_3": "",
                            "registro_ids.estado_visita_2": "",
                            "registro_ids.tipo_motivo": "1",
                            "line_manzana_ids": "",
                            "line_manzana_ids.manzana_id": "1",
                            "line_manzana_ids.zona_id": "",
                            "line_manzana_ids.sector_ial_id": "",
                            "line_manzana_ids.asignado": "",
                            "line_manzana_ids.actor_id": "",
                            "line_manzana_ids.active": "",
                            "capacitacion_id": "1",
                            "capacitacion_id.responsable_id": "",
                            "capacitacion_id.fecha_inicio_proceso": "",
                            "capacitacion_id.fecha_evaluacion": "",
                            "capacitacion_id.temario": "",
                            "capacitacion_id.estado": "1",
                            "capacitacion_id.fecha_capacitacion": "",
                            "message_follower_ids": "",
                            "message_ids": "",
                        },
                        {"lang": "es_PE", "tz": "America/Lima", "uid": uid, "params": {"action": 1189}},
                    ],
                    "kwargs": {},
                },
                "id": idx + 1,
            }

            try:
                resp = session.post(
                    dataset_url,
                    headers={**headers, "Cookie": cookie_header},
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                self.state.dnis_sin_datos.append({"dni": str(dni), "motivo": str(e)})
                continue

            if "error" in data:
                msg = str(data.get("error", {}).get("message", "Error desconocido"))
                self.state.dnis_sin_datos.append({"dni": str(dni), "motivo": msg})
                continue

            result = data.get("result", {}).get("value", {}) or {}

            campos_sql: list[str] = []
            valores_sql: list[Any] = []
            for clave_api, campo_bd in mapeo.items():
                campo_bd = campo_bd.strip()
                if not campo_bd:
                    continue
                try:
                    _validate_identifier(campo_bd, f"Campo BD ({clave_api})")
                except Exception:
                    continue
                valor = result.get(clave_api)
                if valor:
                    campos_sql.append(f"{campo_bd} = %s")
                    valores_sql.append(valor)

            if not campos_sql:
                continue

            query = f"UPDATE {tabla} SET {', '.join(campos_sql)} WHERE {campo_dni} = %s"
            valores_sql.append(dni)

            try:
                cursor = conn.cursor()
                cursor.execute(query, valores_sql)
                conn.commit()
                filas = cursor.rowcount
                self.state.datos_extraidos.append(
                    {
                        "dni": dni,
                        "nombres": result.get("nombres", ""),
                        "apellidos": result.get("apellidos", ""),
                        "fecha_nacimiento": result.get("fecha_nacimiento", ""),
                        "direccion": result.get("direccion", ""),
                        "estado": f"Filas afectadas: {filas}",
                    }
                )
            except Exception as e:
                self.state.dnis_sin_datos.append({"dni": str(dni), "motivo": str(e)})

            progreso = int(((idx + 1) / total) * 100)
            elapsed = time.time() - inicio
            avg = elapsed / (idx + 1)
            remaining = max(0.0, avg * (total - (idx + 1)))
            self.root.after(0, lambda p=progreso, el=elapsed, rem=remaining: self._update_progress(p, el, rem))

        try:
            conn.close()
        except Exception:
            pass

        self.root.after(0, self._on_automatizar_done)

    def _update_progress(self, progreso: int, elapsed: float, remaining: float) -> None:
        self.progress_var.set(progreso)
        self.progress_text.configure(text=f"{progreso}%")
        el_h, el_m = divmod(int(elapsed), 3600)
        el_m, el_s = divmod(el_m, 60)
        rem_h, rem_m = divmod(int(remaining), 3600)
        rem_m, rem_s = divmod(rem_m, 60)
        self.time_text.configure(text=f"Duración: {el_h}h {el_m}m {el_s}s | ETA: {rem_h}h {rem_m}m {rem_s}s")

    def _on_automatizar_done(self) -> None:
        self.log("Proceso finalizado.")
        self._set_running(False)

    def _on_automatizar_error(self, error: str) -> None:
        self.log(f"Error en automatización: {error}")
        messagebox.showerror("Error", error)
        self._set_running(False)

    def exportar_log(self) -> None:
        file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(self._log_registro))
            messagebox.showinfo("Exportado", f"Log guardado en: {file_path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def exportar_resultados(self) -> None:
        if not self.state.datos_extraidos and not self.state.dnis_sin_datos:
            messagebox.showinfo("Sin datos", "No hay resultados para exportar aún.")
            return
        carpeta = filedialog.askdirectory()
        if not carpeta:
            return
        try:
            if self.state.datos_extraidos:
                df_ok = pd.DataFrame(self.state.datos_extraidos)
                df_ok.to_excel(os.path.join(carpeta, "resultados_ok.xlsx"), index=False)
            if self.state.dnis_sin_datos:
                df_err = pd.DataFrame(self.state.dnis_sin_datos)
                df_err.to_excel(os.path.join(carpeta, "resultados_error.xlsx"), index=False)
            messagebox.showinfo("Exportado", f"Archivos guardados en: {carpeta}")
        except Exception as e:
            messagebox.showerror("Error", str(e))


def main() -> None:
    root = _create_root()
    App(root)
    root.mainloop()

