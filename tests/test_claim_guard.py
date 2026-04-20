"""Tests pour le module claim_guard (Chantier 1bis)."""

from fitmas.claim_guard import (
    looks_like_action_claim,
    safe_rewrite_for_claim_without_mutation,
)


class TestLooksLikeActionClaim:
    def test_empty_text_is_not_a_claim(self):
        assert looks_like_action_claim("") is False
        assert looks_like_action_claim(None) is False  # type: ignore[arg-type]

    def test_je_libere_ce_creneau_is_a_claim(self):
        assert looks_like_action_claim(
            "OK. Je libere ce creneau et je garde la suite propre."
        ) is True

    def test_je_libere_with_accent_is_a_claim(self):
        assert looks_like_action_claim("Je libère le créneau.") is True

    def test_je_deplace_seance_is_a_claim(self):
        assert looks_like_action_claim("Je deplace la seance a mercredi.") is True

    def test_je_remplace_is_a_claim(self):
        assert looks_like_action_claim("Je remplace la natation par du running.") is True

    def test_je_supprime_is_a_claim(self):
        assert looks_like_action_claim("Je supprime mercredi.") is True

    def test_je_decale_is_a_claim(self):
        assert looks_like_action_claim("Je decale au lendemain.") is True

    def test_je_ajoute_with_elision_is_a_claim(self):
        assert looks_like_action_claim("J'ajoute un renfo jeudi.") is True

    def test_je_ajoute_typographic_apostrophe_is_a_claim(self):
        assert looks_like_action_claim("J\u2019ajoute un renfo jeudi.") is True

    def test_je_swappe_is_a_claim(self):
        assert looks_like_action_claim("Je swappe lundi et mercredi.") is True

    def test_negation_ne_is_not_a_claim(self):
        assert looks_like_action_claim(
            "Je ne deplace pas la seance sans ton accord."
        ) is False

    def test_negation_n_apostrophe_is_not_a_claim(self):
        assert looks_like_action_claim(
            "Je n'ajoute rien sans validation."
        ) is False

    def test_je_propose_is_not_a_claim(self):
        assert looks_like_action_claim(
            "Je propose de deplacer la seance a mercredi. Ok ?"
        ) is False

    def test_je_peux_is_not_a_claim(self):
        assert looks_like_action_claim(
            "Je peux deplacer la seance si tu veux."
        ) is False

    def test_je_pourrais_is_not_a_claim(self):
        assert looks_like_action_claim(
            "Je pourrais remplacer la natation par du running."
        ) is False

    def test_veux_tu_is_not_a_claim(self):
        assert looks_like_action_claim(
            "Veux-tu que je deplace la seance ?"
        ) is False

    def test_tu_confirmes_is_not_a_claim(self):
        assert looks_like_action_claim(
            "Je deplace la seance a mercredi, tu confirmes ?"
        ) is False

    def test_question_only_is_not_a_claim(self):
        assert looks_like_action_claim(
            "Comment s'est passe ton entrainement hier ?"
        ) is False

    def test_neutral_acknowledgement_is_not_a_claim(self):
        assert looks_like_action_claim("Bien recu.") is False

    def test_je_te_deplace_with_pronoun_is_a_claim(self):
        assert looks_like_action_claim("Je te deplace ca a mercredi.") is True

    def test_je_la_remplace_with_pronoun_is_a_claim(self):
        assert looks_like_action_claim("Je la remplace par du running.") is True


class TestSafeRewrite:
    def test_rewrite_does_not_assert_action(self):
        rewrite = safe_rewrite_for_claim_without_mutation()
        assert "n'ai applique aucun changement" in rewrite

    def test_rewrite_is_not_itself_an_action_claim(self):
        rewrite = safe_rewrite_for_claim_without_mutation()
        assert looks_like_action_claim(rewrite) is False
