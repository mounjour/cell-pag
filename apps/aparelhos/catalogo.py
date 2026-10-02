"""Modelos para os cadastros de estoque e contratos.

Fonte: https://support.apple.com/pt-br/108044 (conferida em 02/10/2026).
Opções de seleção, sem substituir descrições já cadastradas ou a capacidade.
"""

MODELOS_IPHONE = (
    "iPhone 18 Pro", "iPhone 18 Pro Max",
    "iPhone 17", "iPhone 17 Pro", "iPhone 17 Pro Max", "iPhone 17e", "iPhone Air",
    "iPhone 16", "iPhone 16 Plus", "iPhone 16 Pro", "iPhone 16 Pro Max", "iPhone 16e",
    "iPhone 15", "iPhone 15 Plus", "iPhone 15 Pro", "iPhone 15 Pro Max",
    "iPhone 14", "iPhone 14 Plus", "iPhone 14 Pro", "iPhone 14 Pro Max",
    "iPhone 13", "iPhone 13 mini", "iPhone 13 Pro", "iPhone 13 Pro Max",
    "iPhone 12", "iPhone 12 mini", "iPhone 12 Pro", "iPhone 12 Pro Max",
    "iPhone 11", "iPhone 11 Pro", "iPhone 11 Pro Max",
    "iPhone XS", "iPhone XS Max", "iPhone XR", "iPhone X",
    "iPhone SE (3ª geração)", "iPhone SE (2ª geração)", "iPhone SE (1ª geração)",
    "iPhone 8", "iPhone 8 Plus", "iPhone 7", "iPhone 7 Plus",
    "iPhone 6s", "iPhone 6s Plus", "iPhone 6", "iPhone 6 Plus",
    "iPhone 5s", "iPhone 5c", "iPhone 5", "iPhone 4s", "iPhone 4",
    "iPhone 3GS", "iPhone 3G", "iPhone",
)


def opcoes_modelos(atual="", estoque=()):
    """Lista fechada; preserva o valor salvo e as descrições do estoque."""
    modelos = list(MODELOS_IPHONE)
    for modelo in (atual, *estoque):
        if modelo and modelo not in modelos:
            modelos.append(modelo)
    return [("", "Selecione o modelo do iPhone")] + [(modelo, modelo) for modelo in modelos]
