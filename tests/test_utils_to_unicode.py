import src.RPFramework

def test_to_unicode_ascii_string():
    assert src.RPFramework.RPFrameworkUtils.to_unicode('test') == u'test'