# Firebase Realtime Database Schema

- [Users](users.md)
- [Universes](universes.md)

Python schema definitions live in `models.py`; record constructors live in
`factories.py`. New Firebase writes should use a factory when one exists.

All simulation times are expressed in simulation seconds. Object positions use
world units.
