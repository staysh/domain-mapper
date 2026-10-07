import unittest

from mapper import resolve_link


class UrlResolutionTest(unittest.TestCase):
    def test_extensionless_page_resolves_relative_links_as_directory(self):
        self.assertEqual(
            resolve_link("https://www.pcc.edu/instructional-support", "tools"),
            "https://www.pcc.edu/instructional-support/tools",
        )

    def test_file_page_resolves_relative_links_normally(self):
        self.assertEqual(
            resolve_link("https://www.pcc.edu/page.html", "tools"),
            "https://www.pcc.edu/tools",
        )

    def test_root_relative_and_absolute_links_still_work(self):
        self.assertEqual(
            resolve_link("https://www.pcc.edu/instructional-support", "/tools"),
            "https://www.pcc.edu/tools",
        )
        self.assertEqual(
            resolve_link(
                "https://www.pcc.edu/instructional-support",
                "https://www.pcc.edu/contact",
            ),
            "https://www.pcc.edu/contact",
        )


if __name__ == "__main__":
    unittest.main()
