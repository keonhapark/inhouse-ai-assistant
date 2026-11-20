package io.inhouse.erp.room;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "room")
public class Room {

    @Id
    private String id;
    private String name;
    private int floor;
    private int capacity;

    protected Room() {}

    public Room(String id) {
        this.id = id;
    }

    public void update(String name, int floor, int capacity) {
        this.name = name;
        this.floor = floor;
        this.capacity = capacity;
    }

    public String getId() { return id; }
    public String getName() { return name; }
    public int getFloor() { return floor; }
    public int getCapacity() { return capacity; }
}
