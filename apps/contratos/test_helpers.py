from django.urls import reverse


def cadastrar_contrato(client, dados, **kwargs):
    """Percorre a revisão e a confirmação antes de testar os efeitos do cadastro."""
    resposta = client.post(reverse("contratos:novo"), dados)
    if resposta.context and "revisao" in resposta.context:
        return client.post(reverse("contratos:novo"), {
            "revisao": resposta.context["revisao"], "acao": "confirmar", "conferido": "1",
        }, **kwargs)
    return resposta
