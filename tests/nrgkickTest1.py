import unittest
import logging

logging.basicConfig(level=logging.DEBUG)

class TestHelloWorld(unittest.TestCase):

    def setUp(self):
        self.logger = logging.getLogger(__name__)

    def test_example(self):
        self.logger.info('Info message')


        # Ein einfacher Testfall
        self.assertEqual(1 + 1, 2)

if __name__ == '__main__':
    unittest.main()