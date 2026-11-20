package io.inhouse.erp.notification;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface NotificationRepository extends JpaRepository<Notification, String> {

    List<Notification> findByRecipientIdOrderByCreatedAtDescIdDesc(String recipientId);

    List<Notification> findByRecipientIdAndReadFalseOrderByCreatedAtDescIdDesc(String recipientId);
}
