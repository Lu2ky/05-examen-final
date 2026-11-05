"""Lógica de la prueba de vida sobre series sintéticas de landmarks (sin cámara ni rostros reales)."""

import numpy as np

from asistente.biometria import identidad
from asistente.biometria import liveness
from asistente.biometria.liveness import Umbrales, evaluar_movimiento, nuevo_reto

U = Umbrales(espejo=False)


def serie(inicio, fin, n=20):
    return list(np.linspace(inicio, fin, n))


def test_giro_izquierda_y_derecha_distinguen_direccion():
    anchos = [100.0] * 20
    a_izq = serie(0.0, 0.25)   # nariz hacia la derecha de la imagen = giro a TU izquierda (sin espejo)
    a_der = serie(0.0, -0.25)
    assert evaluar_movimiento("izquierda", a_izq, anchos, U)[0]
    assert not evaluar_movimiento("derecha", a_izq, anchos, U)[0]
    assert evaluar_movimiento("derecha", a_der, anchos, U)[0]
    assert not evaluar_movimiento("izquierda", a_der, anchos, U)[0]


def test_modo_espejo_invierte_direccion():
    espejo = Umbrales(espejo=True)
    assert evaluar_movimiento("izquierda", serie(0, -0.25), [100.0] * 20, espejo)[0]


def test_sin_movimiento_se_rechaza():
    assert not evaluar_movimiento("izquierda", [0.01] * 20, [100.0] * 20, U)[0]
    assert not evaluar_movimiento("acercarse", [0.0] * 20, [100.0] * 20, U)[0]


def test_acercarse():
    assert evaluar_movimiento("acercarse", [0.0] * 20, serie(100, 150), U)[0]


def test_reto_aleatorio_con_al_menos_tres_opciones():
    assert len(liveness.RETOS) >= 3
    assert len({nuevo_reto().tipo for _ in range(200)}) == len(liveness.RETOS)


def test_reto_usado_y_vencido_se_rechazan_sin_tocar_el_video():
    r = nuevo_reto(ahora=1000.0)
    assert identidad.verificar_vida(1, "/no/existe.mp4", r, ahora=1000.0 + 10_000) == (False, 0.0, "reto_vencido")
    assert r.usado  # se consume aunque falle
    assert identidad.verificar_vida(1, "/no/existe.mp4", r, ahora=1000.0) == (False, 0.0, "reto_usado")


def test_sin_enrolamiento_se_rechaza():
    r = nuevo_reto()
    ok, sim, motivo = identidad.verificar_vida(999_999_999, "/no/existe.mp4", r)
    assert (ok, motivo) == (False, "sin_enrolamiento")


def test_umbrales_leen_el_entorno_al_crearse_no_al_importar(monkeypatch):
    monkeypatch.setenv("LIVENESS_MIRROR", "1")
    monkeypatch.setenv("LIVENESS_MIN_TURN", "0.2")
    u = Umbrales()
    assert u.espejo is True and u.giro_minimo == 0.2
    monkeypatch.setenv("LIVENESS_MIRROR", "0")
    assert Umbrales().espejo is False
