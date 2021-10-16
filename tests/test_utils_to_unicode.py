import src.RPFramework

def test_to_unicode_ascii_string():
    assert src.RPFramework.RPFrameworkUtils.to_unicode('test') == u'test'

def test_to_unicode_unicode_string():
    assert src.RPFramework.RPFrameworkUtils.to_unicode(u'test') == u'test'

def test_to_unicode_int():
    assert src.RPFramework.RPFrameworkUtils.to_unicode(3) == u'3'

def test_to_unicode_float():
    assert src.RPFramework.RPFrameworkUtils.to_unicode(3.5) == u'3.5'

def test_to_unicode_list():
    x = ['abc', 'def', 'ghi']
    assert src.RPFramework.RPFrameworkUtils.to_unicode(x) == u"['abc', 'def', 'ghi']"

def test_to_unicode_dict():
    dict = {'Name': 'Zara', 'Age': 7}
    assert src.RPFramework.RPFrameworkUtils.to_unicode(dict) == u"{'Name': 'Zara', 'Age': 7}"

def test_to_unicode_complex():
    x = ['abc', 'def', 'ghi']
    dict = {'Name': 'Zara', 'Age': 7, 'Alpha': x}
    assert src.RPFramework.RPFrameworkUtils.to_unicode(dict) == u"{'Name': 'Zara', 'Age': 7, 'Alpha': ['abc', 'def', 'ghi']}"