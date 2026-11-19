import unittest

from pipeline.geometry import geometry_reasons, validate_event_geometry


class GeometryTests(unittest.TestCase):
    def test_row_column_bounds_on_nonsquare_frame(self):
        def point(row, column):
            return {"geometry": {"type": "point", "coordinates": [[row, column]]}}
        self.assertEqual(geometry_reasons(point(99, 199), "point", [(100, 200)]), [])
        for row, column in ((100, 50), (50, 200), (-1, 50), (150, 50)):
            self.assertIn("GEOMETRY_OUT_OF_BOUNDS", geometry_reasons(point(row, column), "point", [(100, 200)]))
        self.assertIn("GEOMETRY_OUT_OF_BOUNDS", geometry_reasons(point(99, 199), "point", [(100, 200), (50, 100)]))

    def test_null_and_geometry_type_requirements(self):
        self.assertEqual(geometry_reasons({"geometry": None}, "none", []), [])
        self.assertEqual(geometry_reasons({}, "none", []), ["MISSING_GEOMETRY"])
        self.assertEqual(geometry_reasons({"geometry": None}, "polygon", []), ["GEOMETRY_TYPE_MISMATCH"])
        shape = {"geometry": {"type": "point", "coordinates": [[1, 2]]}}
        self.assertEqual(geometry_reasons(shape, "polygon", []), ["GEOMETRY_TYPE_MISMATCH"])

    def test_invalid_coordinates_and_point_cardinality(self):
        for coordinates in (None, [], [[True, 2]], [[float("nan"), 2]], [[float("inf"), 2]],
                            [["1", 2]], [[1, 2, 3]], [1, 2], [[10**400, 2]]):
            shape = {"geometry": {"type": "point", "coordinates": coordinates}}
            self.assertIn("INVALID_COORDINATES", geometry_reasons(shape, "point", []))
        shape = {"geometry": {"type": "point", "coordinates": [[1, 2], [3, 4]]}}
        self.assertEqual(geometry_reasons(shape, "point", []), ["INVALID_POINT"])

    def test_polygon_open_closed_and_invalid_shapes(self):
        triangle = [[0, 0], [0, 5], [5, 0]]
        for coordinates in (triangle, triangle + [triangle[0]], list(reversed(triangle))):
            self.assertEqual(geometry_reasons({"geometry": {"type": "polygon", "coordinates": coordinates}}, "polygon", [(10, 10)]), [])
        for coordinates in ([[0, 0], [1, 1]], [[0, 0], [1, 1], [2, 2]],
                            [[0, 0], [4, 4], [0, 4], [3, 0]],
                            [[0, 0], [0, 4], [4, 4], [0, 4], [4, 0]]):
            self.assertIn("INVALID_POLYGON", geometry_reasons({"geometry": {"type": "polygon", "coordinates": coordinates}}, "polygon", [(10, 10)]))

    def test_pair_compatibility_normal_exclusivity_and_instance_position(self):
        frame = dict(roll_id="r1", machine_id="m1", camera_position="c1", light_type="VIS", height_px=100, width_px=200)
        frames = {"a": frame, "b": dict(frame, light_type="IR")}
        taxonomies = {1: {"Normal": ("none", False), "Defect/Hole": ("point", False)}}
        payload = dict(frame_ids=["a", "b"], label_tree_version=1,
                       instances=[{"label": "Defect/Hole", "geometry": {"type": "point", "coordinates": [[10, 150]]}}])
        self.assertEqual(validate_event_geometry(payload, taxonomies, frames), [])
        frames["b"]["height_px"] = 5
        issues = validate_event_geometry(payload, taxonomies, frames)
        self.assertIn({"reason": "INCOMPATIBLE_FRAME_PAIR"}, issues)
        self.assertIn({"reason": "GEOMETRY_OUT_OF_BOUNDS", "instance_index": 0}, issues)
        payload["instances"].append({"label": "Normal", "geometry": None})
        self.assertIn({"reason": "NORMAL_WITH_OTHER_INSTANCES"}, validate_event_geometry(payload, taxonomies, frames))
