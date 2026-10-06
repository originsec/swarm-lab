import hashlib
import unittest
import xml.etree.ElementTree as ET

import dashboard


class BrandingTests(unittest.TestCase):
    def test_header_uses_exact_website_wordmark_artwork(self):
        logo = ET.fromstring(dashboard.LOGO)
        ns = {"svg": "http://www.w3.org/2000/svg"}
        self.assertEqual(logo.get("viewBox"), "0 0 224 52")
        self.assertEqual(logo.find("svg:g", ns).get("transform"),
                         "translate(224 0) rotate(90)")
        path = logo.find("svg:g/svg:path", ns).get("d")
        # Origin website's Wordmark.tsx path, verified against the live home page.
        self.assertEqual(hashlib.sha256(path.encode()).hexdigest(),
                         "8b044b0fb1b764a34a5da8d2e30a07cf84240a40771805597accfa6ce4f9ce43")
        self.assertFalse(logo.findall(".//svg:text", ns))

    def test_wordmark_has_accessible_name(self):
        logo = ET.fromstring(dashboard.LOGO)
        self.assertEqual(logo.get("role"), "img")
        self.assertEqual(logo.get("aria-label"), "Origin Technology")
        self.assertEqual(logo.find("{http://www.w3.org/2000/svg}title").text,
                         "Origin Technology")

    def test_header_does_not_render_a_second_generic_origin_label(self):
        self.assertIn("<div class=brand>__LOGO__</div>", dashboard.PAGE)
        self.assertNotIn("class=product-word", dashboard.PAGE)
        self.assertNotIn(".brand .product-word{display:none}", dashboard.PAGE)
        self.assertIn(".brand svg{width:112px;height:26px", dashboard.PAGE)


if __name__ == "__main__":
    unittest.main()
