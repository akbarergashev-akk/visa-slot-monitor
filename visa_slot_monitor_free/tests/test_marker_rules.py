"""Synthetic tests only; no website is accessed."""
import unittest
from marker_rules import classify_calendar_marks, newly_unrecognized

class MarkerTests(unittest.TestCase):
    def test_closed_days(self):
        payload = {'status':'ok','cells':35,'marks':[
            {'cell':i, 'day':d, 'assets':['icon_disabled.svg']}
            for i,d in [(18,14),(19,15),(20,16),(23,19),(24,20)]
        ]}
        records = classify_calendar_marks(payload)
        self.assertTrue(all(x.classification=='closed' for x in records))
        self.assertEqual(newly_unrecognized([], records), [])

    def test_no_image_not_available(self):
        self.assertEqual(classify_calendar_marks({'status':'ok','cells':35,'marks':[]}), [])

    def test_unrecognized_image_not_assumed_open(self):
        data = {'status':'ok','cells':35,'marks':[{'cell':18,'day':14,'assets':['another.svg']}]}
        records = classify_calendar_marks(data)
        self.assertEqual(records[0].classification, 'needs_review')
        self.assertEqual(newly_unrecognized([], records), records)
        self.assertEqual(newly_unrecognized(records, records), [])

    def test_mixed_unknown(self):
        data = {'status':'ok','cells':35,'marks':[{'cell':18,'day':14,'assets':['icon_disabled.svg','other.svg']}]}
        self.assertEqual(classify_calendar_marks(data)[0].classification, 'needs_review')

    def test_invalid_page_not_accepted(self):
        with self.assertRaises(ValueError):
            classify_calendar_marks({'status':'not_found','cells':0,'marks':[]})

if __name__ == '__main__':
    unittest.main()
