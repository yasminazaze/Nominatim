"""
Tests for converting a config file to ICU rules.
"""
from textwrap import dedent

import pytest
import yaml

from nominatim.tokenizer.icu_rule_loader import ICURuleLoader
from nominatim.errors import UsageError

from icu import Transliterator

@pytest.fixture
def cfgrules():
    def _create_config(*variants, **kwargs):
        content = dedent("""\
        normalization:
            - ":: NFD ()"
            - "[[:Nonspacing Mark:] [:Cf:]] >"
            - ":: lower ()"
            - "[[:Punctuation:][:Space:]]+ > ' '"
            - ":: NFC ()"
        transliteration:
            - "::  Latin ()"
            - "[[:Punctuation:][:Space:]]+ > ' '"
        """)
        content += "variants:\n  - words:\n"
        content += '\n'.join(("      - " + s for s in variants)) + '\n'
        for k, v in kwargs:
            content += "    {}: {}\n".format(k, v)
        return yaml.safe_load(content)

    return _create_config


def test_empty_rule_set():
    rule_cfg = yaml.safe_load(dedent("""\
        normalization:
        transliteration:
        variants:
        """))

    rules = ICURuleLoader(rule_cfg)
    assert rules.get_search_rules() == ''
    assert rules.get_normalization_rules() == ''
    assert rules.get_transliteration_rules() == ''
    assert list(rules.get_replacement_pairs()) == []

CONFIG_SECTIONS = ('normalization', 'transliteration', 'variants')

@pytest.mark.parametrize("section", CONFIG_SECTIONS)
def test_missing_section(section):
    rule_cfg = { s: {} for s in CONFIG_SECTIONS if s != section}

    with pytest.raises(UsageError):
        ICURuleLoader(rule_cfg)


def test_get_search_rules(cfgrules):
    loader = ICURuleLoader(cfgrules())

    rules = loader.get_search_rules()
    trans = Transliterator.createFromRules("test", rules)

    assert trans.transliterate(" Baum straße ") == " baum straße "
    assert trans.transliterate(" Baumstraße ") == " baumstraße "
    assert trans.transliterate(" Baumstrasse ") == " baumstrasse "
    assert trans.transliterate(" Baumstr ") == " baumstr "
    assert trans.transliterate(" Baumwegstr ") == " baumwegstr "
    assert trans.transliterate(" Αθήνα ") == " athēna "
    assert trans.transliterate(" проспект ") == " prospekt "


def test_get_normalization_rules(cfgrules):
    loader = ICURuleLoader(cfgrules())
    rules = loader.get_normalization_rules()
    trans = Transliterator.createFromRules("test", rules)

    assert trans.transliterate(" проспект-Prospekt ") == " проспект prospekt "


def test_get_transliteration_rules(cfgrules):
    loader = ICURuleLoader(cfgrules())
    rules = loader.get_transliteration_rules()
    trans = Transliterator.createFromRules("test", rules)

    assert trans.transliterate(" проспект-Prospekt ") == " prospekt Prospekt "


def test_transliteration_rules_from_file(def_config, tmp_path):
    def_config.project_dir = tmp_path
    cfgpath = tmp_path / ('test_config.yaml')
    cfgpath.write_text(dedent("""\
        normalization:
        transliteration:
            - "'ax' > 'b'"
            - !include transliteration.yaml
        variants:
        """))
    transpath = tmp_path / ('transliteration.yaml')
    transpath.write_text('- "x > y"')

    loader = ICURuleLoader(def_config.load_sub_configuration('test_config.yaml'))
    rules = loader.get_transliteration_rules()
    trans = Transliterator.createFromRules("test", rules)

    assert trans.transliterate(" axxt ") == " byt "


class TestGetReplacements:

    @pytest.fixture(autouse=True)
    def setup_cfg(self, cfgrules):
        self.cfgrules = cfgrules

    def get_replacements(self, *variants):
        loader = ICURuleLoader(self.cfgrules(*variants))
        rules = loader.get_replacement_pairs()

        return set((v.source, v.replacement) for v in rules)


    @pytest.mark.parametrize("variant", ['foo > bar', 'foo -> bar -> bar',
                                         '~foo~ -> bar', 'fo~ o -> bar'])
    def test_invalid_variant_description(self, variant):
        with pytest.raises(UsageError):
            ICURuleLoader(self.cfgrules(variant))

    def test_add_full(self):
        repl = self.get_replacements("foo -> bar")

        assert repl == {(' foo ', ' bar '), (' foo ', ' foo ')}


    def test_replace_full(self):
        repl = self.get_replacements("foo => bar")

        assert repl == {(' foo ', ' bar ')}


    def test_add_suffix_no_decompose(self):
        repl = self.get_replacements("~berg |-> bg")

        assert repl == {('berg ', 'berg '), ('berg ', 'bg '),
                        (' berg ', ' berg '), (' berg ', ' bg ')}


    def test_replace_suffix_no_decompose(self):
        repl = self.get_replacements("~berg |=> bg")

        assert repl == {('berg ', 'bg '), (' berg ', ' bg ')}


    def test_add_suffix_decompose(self):
        repl = self.get_replacements("~berg -> bg")

        assert repl == {('berg ', 'berg '), ('berg ', ' berg '),
                        (' berg ', ' berg '), (' berg ', 'berg '),
                        ('berg ', 'bg '), ('berg ', ' bg '),
                        (' berg ', 'bg '), (' berg ', ' bg ')}


    def test_replace_suffix_decompose(self):
        repl = self.get_replacements("~berg => bg")

        assert repl == {('berg ', 'bg '), ('berg ', ' bg '),
                        (' berg ', 'bg '), (' berg ', ' bg ')}


    def test_add_prefix_no_compose(self):
        repl = self.get_replacements("hinter~ |-> hnt")

        assert repl == {(' hinter', ' hinter'), (' hinter ', ' hinter '),
                        (' hinter', ' hnt'), (' hinter ', ' hnt ')}


    def test_replace_prefix_no_compose(self):
        repl = self.get_replacements("hinter~ |=> hnt")

        assert repl ==  {(' hinter', ' hnt'), (' hinter ', ' hnt ')}


    def test_add_prefix_compose(self):
        repl = self.get_replacements("hinter~-> h")

        assert repl == {(' hinter', ' hinter'), (' hinter', ' hinter '),
                        (' hinter', ' h'), (' hinter', ' h '),
                        (' hinter ', ' hinter '), (' hinter ', ' hinter'),
                        (' hinter ', ' h '), (' hinter ', ' h')}


    def test_replace_prefix_compose(self):
        repl = self.get_replacements("hinter~=> h")

        assert repl == {(' hinter', ' h'), (' hinter', ' h '),
                        (' hinter ', ' h '), (' hinter ', ' h')}


    def test_add_beginning_only(self):
        repl = self.get_replacements("^Premier -> Pr")

        assert repl == {('^ premier ', '^ premier '), ('^ premier ', '^ pr ')}


    def test_replace_beginning_only(self):
        repl = self.get_replacements("^Premier => Pr")

        assert repl == {('^ premier ', '^ pr ')}


    def test_add_final_only(self):
        repl = self.get_replacements("road$ -> rd")

        assert repl == {(' road ^', ' road ^'), (' road ^', ' rd ^')}


    def test_replace_final_only(self):
        repl = self.get_replacements("road$ => rd")

        assert repl == {(' road ^', ' rd ^')}


    def test_decompose_only(self):
        repl = self.get_replacements("~foo -> foo")

        assert repl == {('foo ', 'foo '), ('foo ', ' foo '),
                        (' foo ', 'foo '), (' foo ', ' foo ')}


    def test_add_suffix_decompose_end_only(self):
        repl = self.get_replacements("~berg |-> bg", "~berg$ -> bg")

        assert repl == {('berg ', 'berg '), ('berg ', 'bg '),
                        (' berg ', ' berg '), (' berg ', ' bg '),
                        ('berg ^', 'berg ^'), ('berg ^', ' berg ^'),
                        ('berg ^', 'bg ^'), ('berg ^', ' bg ^'),
                        (' berg ^', 'berg ^'), (' berg ^', 'bg ^'),
                        (' berg ^', ' berg ^'), (' berg ^', ' bg ^')}


    def test_replace_suffix_decompose_end_only(self):
        repl = self.get_replacements("~berg |=> bg", "~berg$ => bg")

        assert repl == {('berg ', 'bg '), (' berg ', ' bg '),
                        ('berg ^', 'bg ^'), ('berg ^', ' bg ^'),
                        (' berg ^', 'bg ^'), (' berg ^', ' bg ^')}


    def test_add_multiple_suffix(self):
        repl = self.get_replacements("~berg,~burg -> bg")

        assert repl == {('berg ', 'berg '), ('berg ', ' berg '),
                        (' berg ', ' berg '), (' berg ', 'berg '),
                        ('berg ', 'bg '), ('berg ', ' bg '),
                        (' berg ', 'bg '), (' berg ', ' bg '),
                        ('burg ', 'burg '), ('burg ', ' burg '),
                        (' burg ', ' burg '), (' burg ', 'burg '),
                        ('burg ', 'bg '), ('burg ', ' bg '),
                        (' burg ', 'bg '), (' burg ', ' bg ')}
